from aws_cdk import (
    Aws,
    Fn,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
    Duration,
    RemovalPolicy,
)
from constructs import Construct

from app_ecosystem.constructs.common.networking import CommonNetworkingConstruct


class CommonStorageConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        common_networking: CommonNetworkingConstruct,
        **kwargs,
    ):
        super().__init__(scope, id, **kwargs)

        # DB Credentials Secret
        self.db_creds_secret = rds.DatabaseSecret(
            self,
            "AppDatabaseCredentials",
            username="appuser",
            dbname="appdb",
        )

        # RDS Serverless Database Cluster
        self.db_cluster = rds.DatabaseCluster(
            self,
            "AppDatabaseCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_17_5
            ),
            vpc=common_networking.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnets=common_networking.vpc.select_subnets(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                ).subnets,
            ),
            security_groups=[common_networking.db_sg],
            credentials=rds.Credentials.from_secret(
                self.db_creds_secret,
            ),
            default_database_name="appdb",
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=2,
            serverless_v2_auto_pause_duration=Duration.minutes(5),
            removal_policy=RemovalPolicy.DESTROY,
            writer=rds.ClusterInstance.serverless_v2("AppDatabaseWriterInstance"),
        )

        # Valkey serverless (private in VPC) 

        # 1) Valkey SG：allow ECS sg 6379
        self.valkey_sg = ec2.SecurityGroup(
            self, "ValkeySG",
            vpc=common_networking.vpc,
            description="Allow ECS services to access Valkey on 6379",
            allow_all_outbound=True,
        )
        self.valkey_sg.add_ingress_rule(
            peer=common_networking.ecs_sg,           
            connection=ec2.Port.tcp(6379),
            description="ECS services -> Valkey (6379)",
        )

        # 2) choose private subnet
        _priv_egress_subnets = common_networking.vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        ).subnets
        _subnet_ids = [s.subnet_id for s in _priv_egress_subnets]

        # 3) Create Serverless Valkey 
        self.valkey = elasticache.CfnServerlessCache(
            self, "ValkeyServerless",
            engine="valkey",
            serverless_cache_name=f"{Aws.STACK_NAME}-valkey",
            subnet_ids=_subnet_ids,
            security_group_ids=[self.valkey_sg.security_group_id],
          
        )

        # 4) export Endpoint
        self.valkey_endpoint_address = Fn.get_att(self.valkey.logical_id, "Endpoint.Address").to_string()
        self.valkey_endpoint_port = Fn.get_att(self.valkey.logical_id, "Endpoint.Port").to_string()
    