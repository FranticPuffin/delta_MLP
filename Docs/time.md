输入数据修改：
{"mission_id": "DSCO", "total_requested_hr": 1.0, "base_priority": 2, "activities": [{"activity_id": "DSCO_ACT_00", "d_min": 1.0, "d_max": 1.0, "prior": 2, "setup_min": 60, "teardown_min": 15, "can_split": false, "view_periods": [{"antenna": "DSS-23", "start_hr": 56.86, "end_hr": 58.39}]}]}
去除时段优先级"priority_schedule，增加小活动优先级prior


增加接口

输入数据格式：
{"mission_id": "DSCO","activities":[{"activity_id": "DSCO_ACT_00","ask_view":{"start_hr":30.02,"end_hr":50.43}},{"activity_id": "DSCO_ACT_01","ask_view":{"start_hr":30.02,"end_hr":50.43}},{"activity_id": "DSCO_ACT_02","ask_view":{"start_hr":30.02,"end_hr":50.43}},{"activity_id": "DSCO_ACT_03","ask_view":{"start_hr":30.02,"end_hr":50.43}}]}
根据此格式数据修改dsn_data.jsonl，若"mission_id"，"activity_id"可查询，则将"view_periods"截断，每一条{"antenna": "DSS-23", "start_hr": 56.86, "end_hr": 58.39}，其start_hr不能晚于ask_view的end_hr，若超过则截断，将其start_hr替换为ask_view的end_hr,其end_hr不能早于ask_view的start_hr，如果超过截断其end_hr替换为ask_view的start_hr,若不在范围内，则直接删掉这条数据。
例如{"mission_id": "DSCO", "total_requested_hr": 1.0, "base_priority": 2, "activities": [{"activity_id": "DSCO_ACT_00", "d_min": 1.0, "d_max": 1.0, "prior": 2, "setup_min": 60, "teardown_min": 15, "can_split": false, "view_periods": [{"antenna": "DSS-23", "start_hr": 56.86, "end_hr": 58.39}]}]}会被修改为{"mission_id": "DSCO", "total_requested_hr": 1.0, "base_priority": 2, "activities": [{"activity_id": "DSCO_ACT_00", "d_min": 1.0, "d_max": 1.0, "prior": 2, "setup_min": 60, "teardown_min": 15, "can_split": false, "view_periods": []}]}