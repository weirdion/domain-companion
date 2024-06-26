import json
import re
from dataclasses import dataclass
from logging import Logger
from typing import List, Dict

import boto3

DOMAIN_MAP_SSM = "DomainMapConfig"
EMAIL_FORMAT = r"([a-zA-Z0-9_]+)[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)"
log = Logger(name="RedirectLambda")


@dataclass
class RedirectConfig:
	sub_domain: str
	target_domain: str
	uri_map: Dict[str, str]

	@classmethod
	def from_config(cls, obj) -> "RedirectConfig":
		return RedirectConfig(
			sub_domain=obj["subDomain"],
			target_domain=obj["targetDomain"],
			uri_map=obj.get("uri", {}),
		)


@dataclass
class EmailConfig:
	from_sender: str
	alias: str
	recipients: List[str]
	subject_prefix: str

	def get_recipients(self):
		return ", ".join(self.recipients)

	@classmethod
	def from_config(cls, obj) -> "EmailConfig":
		return EmailConfig(
			from_sender=obj["fromSender"],
			alias=obj["alias"],
			recipients=obj["recipients"],
			subject_prefix=obj.get("subjectPrefix", ""),
		)


@dataclass
class DomainMapConfig:
	host_zone_name: str
	hosted_zone_id: str
	redirects: List[RedirectConfig]
	bounce_email: str
	emails: List[EmailConfig]

	@classmethod
	def from_dict(cls, d_map: dict) -> "DomainMapConfig":
		_redirects = []
		if d_map.get("redirects"):
			for r in d_map["redirects"]:
				_redirects.append(RedirectConfig.from_config(r))

		_emails = []
		if d_map.get("emails"):
			for r in d_map["emails"]:
				_emails.append(EmailConfig.from_config(r))
		return DomainMapConfig(
			host_zone_name=d_map["hostZoneName"],
			hosted_zone_id=d_map["hostedZoneId"],
			redirects=_redirects,
			bounce_email=d_map.get("bounceEmail", ""),
			emails=_emails,
		)


class SSMHandler:
	def __init__(self, ssm_name: str = DOMAIN_MAP_SSM):
		self.ssm_client = boto3.client(service_name="ssm", region_name="us-east-1")
		response = self.ssm_client.get_parameter(Name=ssm_name, WithDecryption=True)
		self.domain_map_raw = response["Parameter"]["Value"]
		domain_map_dict_list = json.loads(self.domain_map_raw)
		self.domain_map_config: List[DomainMapConfig] = []
		for d_map in domain_map_dict_list:
			self.domain_map_config.append(DomainMapConfig.from_dict(d_map))

	def get_recipients_for_address(self, to_address: str):
		# -1 to get the last tuple and ignore naming like Ankit <ankit@example.com>
		result = re.findall(EMAIL_FORMAT, to_address)
		domain_name = result[-1][1]
		sanitized_to_address = "@".join(re.findall(EMAIL_FORMAT, to_address)[-1])

		for domain_config in self.domain_map_config:
			if domain_config.host_zone_name == domain_name:
				for e_map in domain_config.emails:
					if sanitized_to_address == e_map.alias:
						log.info(f"Mapping To address from: {to_address} -> {e_map.alias} -> {e_map.recipients}")
						return e_map
		return None
