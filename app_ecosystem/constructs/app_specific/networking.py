from aws_cdk import (
    Duration,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_actions as elbv2_actions,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
)
from constructs import Construct

from app_ecosystem.stacks.common_infra import CommonInfraStack
from app_ecosystem.constructs.app_specific.compute import AppSpecificComputeConstruct
from app_ecosystem.constructs.app_specific.auth import AppSpecificAuthConstruct


class AppSpecificNetworkingConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        common_infra: CommonInfraStack,
        app_compute: AppSpecificComputeConstruct,
        app_auth: AppSpecificAuthConstruct,
        app_config: dict,
        **kwargs,
    ):
        super().__init__(scope, id, **kwargs)

        self.app_config = app_config

        # DNS record to resolve app domain to the ALB
        self.route53_record = self.create_route53_record(common_infra)

        self.host_header = (
            f"{self.app_config['name']}.{common_infra.networking.hosted_zone.zone_name}"
        )

        # Target group for ALB to route backend (API) traffic to ECS service
        self.ecs_target_group = elbv2.ApplicationTargetGroup(
            self,
            f"{self.app_config['name'].title()}ECSTargetGroup",
            vpc=common_infra.networking.vpc,
            port=app_compute.primary_port,   
            target_type=elbv2.TargetType.IP, 
        )
        self.ecs_target_group.add_target(
            app_compute.ecs_service.load_balancer_target(
                container_name=app_compute.primary_container_name,
                container_port=app_compute.primary_port,
            )
        )

        # Add backend ECS traffic rule to common ALB listener
        self.ecs_listener_rule = self.add_listener_rule(
            common_infra=common_infra,
            app_auth=app_auth,
            rule_type="ECS",
            target_group=self.ecs_target_group,
            host_header=self.host_header,
            path_pattern="/api/*",
        )

        # Add frontend S3 traffic rule to common ALB listener
        self.s3_listener_rule = self.add_listener_rule(
            common_infra=common_infra,
            app_auth=app_auth,
            rule_type="S3",
            target_group=common_infra.networking.s3_vpc_endpoint_target_group,
            host_header=self.host_header,
            path_pattern="",  # No specific path pattern for S3 traffic
        )

    def create_route53_record(self, common_infra: CommonInfraStack) -> route53.ARecord:
        record_name = (
            f"{self.app_config['name']}.{common_infra.networking.hosted_zone.zone_name}"
        )
        return route53.ARecord(
            self,
            f"{self.app_config['name'].title()}Record",
            zone=common_infra.networking.hosted_zone,
            record_name=record_name,
            target=route53.RecordTarget.from_alias(
                route53_targets.LoadBalancerTarget(common_infra.networking.alb)
            ),
        )

    def add_listener_rule(
        self,
        common_infra: CommonInfraStack,
        app_auth: AppSpecificAuthConstruct,
        rule_type: str,
        target_group: elbv2.ApplicationTargetGroup,
        host_header: str,
        path_pattern: str = "",
    ) -> elbv2.ApplicationListenerRule:
        # Get latest rule priority number for this app's priority band
        rule_priority = common_infra.networking.get_rule_priority_for_band(
            self.app_config["alb_priority_band"]
        )

        # Build conidtions list dynamically
        conditions = [elbv2.ListenerCondition.host_headers(values=[host_header])]
        if path_pattern:
            conditions.append(
                elbv2.ListenerCondition.path_patterns(values=[path_pattern])
            )

        return elbv2.ApplicationListenerRule(
            self,
            f"{self.app_config['name'].title()}{rule_type}ListenerRule",
            listener=common_infra.networking.https_listener,
            priority=rule_priority,
            conditions=conditions,
            action=elbv2_actions.AuthenticateCognitoAction(
                user_pool=app_auth.user_pool,
                user_pool_client=app_auth.user_pool_client,
                user_pool_domain=app_auth.user_pool_domain,
                session_cookie_name=f"{self.app_config['name'].title()}AWSELBAuthSessionCookie",
                session_timeout=Duration.seconds(604800),
                next=elbv2.ListenerAction.forward(target_groups=[target_group]),
            ),
        )
