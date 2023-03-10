# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# isort:skip_file
import copy
import json
import time
from unittest.mock import patch
import pytest

import tests.integration_tests.test_app  # pylint: disable=unused-import
from superset import db, security_manager
from superset.dashboards.dao import DashboardDAO
from superset.models.dashboard import Dashboard
from tests.integration_tests.base_tests import SupersetTestCase
from tests.integration_tests.fixtures.world_bank_dashboard import (
    load_world_bank_dashboard_with_slices,
    load_world_bank_data,
)


class TestDashboardDAO(SupersetTestCase):
    @pytest.mark.usefixtures("load_world_bank_dashboard_with_slices")
    def test_set_dash_metadata(self):
        dash: Dashboard = (
            db.session.query(Dashboard).filter_by(slug="world_health").first()
        )
        data = dash.data
        positions = data["position_json"]
        data.update({"positions": positions})
        original_data = copy.deepcopy(data)

        # add filter scopes
        filter_slice = next(slc for slc in dash.slices if slc.viz_type == "filter_box")
        immune_slices = [slc for slc in dash.slices if slc != filter_slice]
        filter_scopes = {
            str(filter_slice.id): {
                "region": {
                    "scope": ["ROOT_ID"],
                    "immune": [slc.id for slc in immune_slices],
                }
            }
        }
        data.update({"filter_scopes": json.dumps(filter_scopes)})
        DashboardDAO.set_dash_metadata(dash, data)
        updated_metadata = json.loads(dash.json_metadata)
        self.assertEqual(updated_metadata["filter_scopes"], filter_scopes)

        # remove a slice and change slice ids (as copy slices)
        removed_slice = immune_slices.pop()
        removed_components = [
            key
            for (key, value) in positions.items()
            if isinstance(value, dict)
            and value.get("type") == "CHART"
            and value["meta"]["chartId"] == removed_slice.id
        ]
        for component_id in removed_components:
            del positions[component_id]

        data.update({"positions": positions})
        DashboardDAO.set_dash_metadata(dash, data)
        updated_metadata = json.loads(dash.json_metadata)
        expected_filter_scopes = {
            str(filter_slice.id): {
                "region": {
                    "scope": ["ROOT_ID"],
                    "immune": [slc.id for slc in immune_slices],
                }
            }
        }
        self.assertEqual(updated_metadata["filter_scopes"], expected_filter_scopes)

        # reset dash to original data
        DashboardDAO.set_dash_metadata(dash, original_data)

    @pytest.mark.usefixtures("load_world_bank_dashboard_with_slices")
    @patch("superset.utils.core.g")
    @patch("superset.security.manager.g")
    def test_get_dashboard_changed_on(self, mock_sm_g, mock_g):
        mock_g.user = mock_sm_g.user = security_manager.find_user("admin")
        with self.client.application.test_request_context():
            self.login(username="admin")
            dashboard = (
                db.session.query(Dashboard).filter_by(slug="world_health").first()
            )

            changed_on = dashboard.changed_on.replace(microsecond=0)
            assert changed_on == DashboardDAO.get_dashboard_changed_on(dashboard)
            assert changed_on == DashboardDAO.get_dashboard_changed_on("world_health")

            old_changed_on = dashboard.changed_on

            # freezegun doesn't work for some reason, so we need to sleep here :(
            time.sleep(1)
            data = dashboard.data
            positions = data["position_json"]
            data.update({"positions": positions})
            original_data = copy.deepcopy(data)

            data.update({"foo": "bar"})
            DashboardDAO.set_dash_metadata(dashboard, data)
            db.session.merge(dashboard)
            db.session.commit()
            new_changed_on = DashboardDAO.get_dashboard_changed_on(dashboard)
            assert old_changed_on.replace(microsecond=0) < new_changed_on
            assert new_changed_on == DashboardDAO.get_dashboard_and_datasets_changed_on(
                dashboard
            )
            assert new_changed_on == DashboardDAO.get_dashboard_and_slices_changed_on(
                dashboard
            )

            DashboardDAO.set_dash_metadata(dashboard, original_data)
            db.session.merge(dashboard)
            db.session.commit()
