import json
import operator
from .base_classes import ObjectWithArn, IAM
from collections import namedtuple

__all__ = ["IamRole"]


# noinspection PyPropertyAccess,PyAttributeOutsideInit
class IamRole(ObjectWithArn):
    """Class for defining AWS IAM Roles"""
    def __init__(self, name, description=None, service='ecs-tasks',
                 policies=(), add_instance_profile=False, verbosity=0):
        """ Initialize an AWS IAM Role object.

        Parameters
        ----------
        name : string
            Name of the IAM role

        description : string
            description of this IAM role
            If description == None (default), then it is reset to
            "This role was generated by cloudknot"
            Default: None

        service : {'ecs-tasks', 'batch', 'ec2', 'lambda', 'spotfleet'}
            service role on which this AWS IAM role should be based.
            Default: 'ecs-tasks'

        policies : tuple of strings
            tuple of names of AWS policies to attach to this role
            Default: ()

        add_instance_profile : boolean
            flag to create an AWS instance profile and attach this role to it
            Default: False

        verbosity : int
            verbosity level [0, 1, 2]
        """
        super(IamRole, self).__init__(name=name, verbosity=verbosity)

        role_exists = self._exists_already()
        self._pre_existing = role_exists.exists

        if role_exists.exists:
            self._description = role_exists.description
            self._service = None
            self._role_policy_document = role_exists.role_policy_document
            self._policies = role_exists.policies
            self._add_instance_profile = role_exists.add_instance_profile
            self._arn = role_exists.arn
        else:
            if description:
                self._description = str(description)
            else:
                self._description = 'This role was generated by cloudknot'

            if service in self._allowed_services:
                self._service = service + '.amazonaws.com'
            else:
                raise Exception('service must be in ', self._allowed_services)

            role_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": self._service
                    },
                    "Action": "sts:AssumeRole"
                }]
            }
            self._role_policy_document = role_policy

            # Check the user supplied policies against the available policies
            # Remove redundant entries
            response = IAM.list_policies()
            aws_policies = [d['PolicyName'] for d in response.get('Policies')]

            if isinstance(policies, str):
                input_policies = {policies}
            elif all(isinstance(x, str) for x in policies):
                input_policies = set(list(policies))
            else:
                raise Exception('policies must be a string or a '
                                'sequence of strings.')

            if not (input_policies < set(aws_policies)):
                raise Exception('each policy must be an AWS managed policy: ',
                                aws_policies)
            else:
                self._policies = tuple(input_policies)

            if isinstance(add_instance_profile, bool):
                self._add_instance_profile = add_instance_profile
            else:
                raise Exception('add_instance_profile is a boolean input')

            self._arn = self._create()

    _allowed_services = ['batch', 'ec2', 'ecs-tasks', 'lambda', 'spotfleet']

    pre_existing = property(operator.attrgetter('_pre_existing'))
    description = property(operator.attrgetter('_description'))
    service = property(operator.attrgetter('_service'))
    role_policy_document = property(
        operator.attrgetter('_role_policy_document')
    )
    add_instance_profile = property(operator.attrgetter(
        '_add_instance_profile'
    ))
    policies = property(operator.attrgetter('_policies'))

    def _exists_already(self):
        """ Check if an IAM Role exists already

        If role exists, return namedtuple with role info. Otherwise, set the
        namedtuple's `exists` field to `False`. The remaining fields default
        to `None`.

        Returns
        -------
        namedtuple RoleExists
            A namedtuple with fields ['exists', 'description',
            'role_policy_document', 'policies', 'add_instance_profile', 'arn']
        """
        # define a namedtuple for return value type
        RoleExists = namedtuple(
            'RoleExists',
            ['exists', 'description', 'role_policy_document', 'policies',
             'add_instance_profile', 'arn']
        )
        # make all but the first value default to None
        RoleExists.__new__.__defaults__ = \
            (None,) * (len(RoleExists._fields) - 1)

        try:
            response = IAM.get_role(RoleName=self.name)
            arn = response.get('Role')['Arn']
            try:
                description = response.get('Role')['Description']
            except KeyError:
                description = ''
            role_policy = response.get('Role')['AssumeRolePolicyDocument']

            response = IAM.list_attached_role_policies(RoleName=self.name)
            attached_policies = response.get('AttachedPolicies')
            policies = tuple([d['PolicyName'] for d in attached_policies])

            if self.verbosity > 0:
                print('IAM role {name:s} already exists: {arn:s}'.format(
                    name=self.name, arn=arn
                ))

            return RoleExists(
                exists=True, description=description,
                role_policy_document=role_policy, policies=policies,
                add_instance_profile=False, arn=arn
            )
        except IAM.exceptions.NoSuchEntityException:
            return RoleExists(exists=False)

    def _create(self):
        """ Create AWS IAM role using instance parameters

        Returns
        -------
        string
            Amazon Resource Number (ARN) for the created IAM role
        """
        response = IAM.create_role(
            RoleName=self.name,
            AssumeRolePolicyDocument=json.dumps(self.role_policy_document),
            Description=self.description
        )
        role_arn = response.get('Role')['Arn']
        if self.verbosity > 0:
            print('Created role {name:s} with arn {arn:s}'.format(
                name=self.name, arn=role_arn
            ))

        policy_response = IAM.list_policies()
        for policy in self.policies:
            policy_filter = list(filter(
                lambda p: p['PolicyName'] == policy,
                policy_response.get('Policies')
            ))

            policy_arn = policy_filter[0]['Arn']

            IAM.attach_role_policy(
                PolicyArn=policy_arn,
                RoleName=self.name
            )

            if self.verbosity > 0:
                print('Attached policy {policy:s} to role {role:s}'.format(
                    policy=policy, role=self.name
                ))

        if self.add_instance_profile:
            instance_profile_name = self.name + '-instance-profile'
            IAM.create_instance_profile(
                InstanceProfileName=instance_profile_name
            )

            IAM.add_role_to_instance_profile(
                InstanceProfileName=instance_profile_name,
                RoleName=self.name
            )

            if self.verbosity > 0:
                print('Created instance profile {name:s}'.format(
                    name=instance_profile_name
                ))

        return role_arn

    @property
    def instance_profile_arn(self):
        response = IAM.list_instance_profiles_for_role(RoleName=self.name)

        if response.get('InstanceProfiles'):
            # This role has instance profiles, return the first
            arn = response.get('InstanceProfiles')[0]['Arn']
            return arn
        else:
            # This role has no instance profiles, return None
            return None

    def remove_aws_resource(self):
        """ Delete this AWS IAM role

        Returns
        -------
        None
        """
        if self.add_instance_profile:
            response = IAM.list_instance_profiles_for_role(RoleName=self.name)

            instance_profile_name = response.get(
                'InstanceProfiles'
            )[0]['InstanceProfileName']
            IAM.remove_role_from_instance_profile(
                InstanceProfileName=instance_profile_name,
                RoleName=self.name
            )
            IAM.delete_instance_profile(
                InstanceProfileName=instance_profile_name
            )

        policy_response = IAM.list_policies()
        for policy in self.policies:
            policy_filter = list(filter(
                lambda p: p['PolicyName'] == policy,
                policy_response.get('Policies')
            ))

            policy_arn = policy_filter[0]['Arn']

            IAM.detach_role_policy(
                RoleName=self.name,
                PolicyArn=policy_arn
            )

        IAM.delete_role(RoleName=self.name)

        if self.verbosity > 0:
            print('Deleted role {name:s}'.format(
                name=self.name
            ))