# Copyright 2013 mysqlapi authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

from django.test import TestCase
from django.test.client import RequestFactory

from mysqlapi.api.models import Instance
from mysqlapi.api.tests import mocks
from mysqlapi.api.views import Healthcheck

import mock


class HealthcheckTestCase(TestCase):

    def setUp(self):
        self.instance = Instance.objects.create(name="g8mysql",
                                                state="running")

    def tearDown(self):
        self.instance.delete()

    def test_healthcheck_returns_204_if_the_mysql_server_is_on(self):
        request = RequestFactory().get("/resources/g8mysql/status/")
        with mock.patch("mysqlapi.api.models.DatabaseManager.is_up") as is_up:
            is_up.return_value = True
            view = Healthcheck()
            fake = mocks.FakeEC2Client()
            view._client = fake
            response = view.get(request, "g8mysql")
        self.assertEqual(204, response.status_code)

    def test_healthcheck_returns_500_if_the_mysql_server_is_off(self):
        request = RequestFactory().get("/resources/g8mysql/status/")
        with mock.patch("mysqlapi.api.models.DatabaseManager.is_up") as is_up:
            is_up.return_value = False
            view = Healthcheck()
            fake = mocks.FakeEC2Client()
            view._client = fake
            response = view.get(request, "g8mysql")
        self.assertEqual(500, response.status_code)

    def test_healthcheck_returns_201_when_ec2_instance_is_running(self):
        request = RequestFactory().get("/resources/g8mysql/status/")
        with mock.patch("mysqlapi.api.models.DatabaseManager.is_up") as is_up:
            is_up.return_value = True
            view = Healthcheck()
            fake = mocks.FakeEC2Client()
            view._client = fake
            response = view.get(request, "g8mysql")
        self.assertEqual(204, response.status_code)

    def test_healthcheck_doesnt_touch_ec2_when_instance_is_pending(self):
        self.instance.state = "pending"
        self.instance.save()
        request = RequestFactory().get("/resources/g8mysql/status/")
        view = Healthcheck()
        fake = mocks.FakeEC2ClientPendingInstance()
        view._client = fake

        response = view.get(request, "g8mysql")
        self.assertEqual(202, response.status_code)
        self.assertEqual([], fake.actions)
