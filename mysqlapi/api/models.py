# Copyright 2013 mysqlapi authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import hashlib
import os
import re
import subprocess

import MySQLdb

from django.conf import settings
from django.db import models

from mysqlapi.api import creator
from mysqlapi.api.database import Connection


class InvalidInstanceName(Exception):

    def __init__(self, name):
        self.args = [u"%s is a invalid name."]


class InstanceAlreadyExists(Exception):

    def __init__(self, name):
        self.args = [u"Instance %s already exists." % name]


class DatabaseCreationException(BaseException):
    pass


def generate_password(string):
    return hashlib.sha1(string + settings.SALT).hexdigest()


def generate_user(username):
    if len(username) > 16:
        _username = username[:12] + generate_password(username)[:4]
    else:
        _username = username
    return _username


class DatabaseManager(object):

    def __init__(self,
                 name,
                 host="localhost",
                 user="root",
                 password="",
                 public_host=None):
        self.name = canonicalize_db_name(name)
        self._host = host
        self.port = '3306'
        self.conn = Connection(self._host, user, password, "")
        self._public_host = public_host

    @property
    def public_host(self):
        if self._public_host:
            return self._public_host
        return self.host

    def create_database(self):
        self.conn.open()
        cursor = self.conn.cursor()
        sql = "CREATE DATABASE %s default character set utf8 " + \
              "default collate utf8_general_ci"
        cursor.execute(sql % self.name)
        self.conn.close()

    def drop_database(self):
        self.conn.open()
        cursor = self.conn.cursor()
        cursor.execute("DROP DATABASE %s" % self.name)
        self.conn.close()

    def create_user(self, username, host):
        self.conn.open()
        cursor = self.conn.cursor()
        username = generate_user(username)
        password = generate_password(username)
        sql = "grant all privileges on {0}.* to '{1}'@'%' identified by '{2}'"
        cursor.execute(sql.format(self.name, username, password))
        self.conn.close()
        return username, password

    def drop_user(self, username, host):
        self.conn.open()
        cursor = self.conn.cursor()
        cursor.execute("drop user '{0}'@'%'".format(username))
        self.conn.close()

    def export(self):
        cmd = ["mysqldump", "-u", "root", "-d", self.name, "--compact"]
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def is_up(self):
        try:
            self.conn.open()
            return True
        except:
            return False
        finally:
            self.conn.close()

    @property
    def host(self):
        if self._host == "localhost":
            return os.environ.get("MYSQLAPI_DATABASE_HOST", "localhost")
        return self._host


class Instance(models.Model):
    STATE_CHOICES = (
        ("pending", "pending"),
        ("running", "running"),
        ("error", "error"),
    )

    name = models.CharField(max_length=100, unique=True)
    ec2_id = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=50,
                             default="pending",
                             choices=STATE_CHOICES)
    reason = models.CharField(max_length=1000,
                              null=True,
                              blank=True,
                              default=None)
    host = models.CharField(max_length=50, null=True, blank=True)
    port = models.CharField(max_length=5, default="3306")
    shared = models.BooleanField(default=False)

    def is_up(self):
        if self.state == "running" and self.db_manager().is_up():
            return True
        return False

    def db_manager(self):
        host = self.host
        user = "root"
        password = ""
        public_host = None
        if self.shared:
            host = settings.SHARED_SERVER
            user = settings.SHARED_USER
            password = settings.SHARED_PASSWORD
            public_host = settings.SHARED_SERVER_PUBLIC_HOST
        return DatabaseManager(self.name,
                               host=host,
                               user=user,
                               password=password,
                               public_host=public_host)


def _create_shared_database(instance):
    db = DatabaseManager(
        name=instance.name,
        host=settings.SHARED_SERVER,
        user=settings.SHARED_USER,
        password=settings.SHARED_PASSWORD,
    )
    try:
        db.create_database()
    except MySQLdb.ProgrammingError as e:
        if len(e.args) > 1 and "database exists" in e.args[1]:
            raise InstanceAlreadyExists(name=instance.name)
        raise
    instance.state = "running"
    instance.shared = True
    instance.ec2_id = None
    instance.save()


def _create_dedicate_database(instance, ec2_client):
    if not ec2_client.run(instance):
        raise DatabaseCreationException(instance,
                                        "Failed to create EC2 instance.")
    instance.save()
    creator.enqueue(instance)


def create_database(instance, ec2_client=None):
    instance.name = canonicalize_db_name(instance.name)
    if instance.name in settings.RESERVED_NAMES:
        raise InvalidInstanceName(name=instance.name)
    if Instance.objects.filter(name=instance.name):
        raise InstanceAlreadyExists(name=instance.name)
    if settings.SHARED_SERVER:
        return _create_shared_database(instance)
    else:
        return _create_dedicate_database(instance, ec2_client)


def canonicalize_db_name(name):
    if re.search(r"[\W\s]", name) is not None:
        prefix = hashlib.sha1(name).hexdigest()[:10]
        name = re.sub(r"[\W\s]", "_", name) + prefix
    return name
