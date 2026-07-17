"""EC2가 꺼진 채 RDS만 켜져 있으면 RDS를 정지한다.

RDS(blog-db)는 publicly_accessible=false라 EC2 보안그룹을 통해서만 닿는다.
즉 EC2가 stopped인데 RDS가 available인 상태는 '아무도 못 쓰는데 크레딧만 나가는'
상태다 — 유일한 클라이언트가 없으니 켜둘 이유가 없다.

이 상태가 생기는 두 경로:
  1. AWS가 정지된 RDS를 7일 뒤 자동으로 되살린다(정책, 끌 수 없음).
  2. 작업 후 EC2만 끄고 RDS를 깜빡한다.

둘 다 '사람이 매번 기억해야' 막히는 구조라 언젠가 반드시 샌다. 그래서 자동화한다.
"""

import os

import boto3

EC2_INSTANCE_ID = os.environ["EC2_INSTANCE_ID"]
DB_INSTANCE_ID = os.environ["DB_INSTANCE_ID"]

ec2 = boto3.client("ec2")
rds = boto3.client("rds")


def handler(event, context):
    reservations = ec2.describe_instances(InstanceIds=[EC2_INSTANCE_ID])["Reservations"]
    ec2_state = reservations[0]["Instances"][0]["State"]["Name"]

    # 'stopped'일 때만 움직인다. pending/stopping 같은 과도상태는 건드리지 않는다 —
    # 방금 EC2를 켠 사람의 DB를 꺼버리는 일을 막는다(판단이 애매하면 아무것도 안 함).
    if ec2_state != "stopped":
        print(f"skip: EC2={ec2_state} (stopped 아님 → 백엔드가 DB를 쓰는 중일 수 있음)")
        return {"action": "skip", "reason": "ec2_not_stopped", "ec2": ec2_state}

    db_status = rds.describe_db_instances(DBInstanceIdentifier=DB_INSTANCE_ID)[
        "DBInstances"
    ][0]["DBInstanceStatus"]

    # stopped/stopping이면 할 일 없음. starting 등 과도상태도 건드리지 않는다.
    if db_status != "available":
        print(f"skip: RDS={db_status} (available 아님)")
        return {"action": "skip", "reason": "rds_not_available", "rds": db_status}

    rds.stop_db_instance(DBInstanceIdentifier=DB_INSTANCE_ID)
    print(f"stopped: RDS={DB_INSTANCE_ID} (EC2가 stopped인데 available이었음)")
    return {"action": "stopped", "rds": DB_INSTANCE_ID}
