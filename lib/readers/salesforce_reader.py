import collections
import json
import os
from config import config, logging

import click
import requests

from lib.commands.execute import app_default_options
from lib.readers.reader import BaseReader
from lib.streams.json_stream import JSONStream


@click.command(name="salesforce")
@click.option("--salesforce-name")
@click.option("--salesforce-credentials")
@click.option("--salesforce-query")
@app_default_options
def salesforce(**kwargs):
    credentials_path = os.path.join(config.get("SECRETS_PATH"), kwargs.get("salesforce_credentials"))
    with open(credentials_path) as json_file:
        credentials_dict = json.loads(json_file.read())
        return SalesforceReader(
            kwargs.get("salesforce_name"),
            credentials_dict,
            kwargs.get("salesforce_query")
        )


class SalesforceReader(BaseReader):

    _stream = JSONStream

    def __init__(self, name, credentials, query):
        self._name = name

        self._key = credentials['consumer_key']
        self._secret = credentials['consumer_secret']
        self._user = credentials['login']
        self._password = credentials['password']

        self._redirect_uri = config["SALESFORCE_LOGIN_SUCCESS"]
        self._endpoint = config["SALESFORCE_QUERY_ENDPOINT"]
        self._query = query

    def list(self):
        return [self._endpoint]

    def connect(self):
        params = self.format_params()
        res = requests.post(config["SALESFORCE_LOGIN_ENDPOINT"], params=params)
        self._access_token = res.json().get("access_token")
        self._instance_url = res.json().get("instance_url")
        logging.info("Getting access_token {} and instance_url {}".format(self._access_token, self._instance_url))

    def read(self, endpoint):
        res = self._request_data(
            endpoint,
            params=self.format_query(self._query)
        )
        records = res.json()['records']

        while "nextRecordsUrl" in res.json():
            res = self._request_data(res.json()['nextRecordsUrl'])
            records = records + res.json()['records']
            if res.status_code != 200:
                raise Exception(res.json())

        return self._name, self._clean_results(records)

    def _clean_results(self, records):
        """
            Salesforces records contains metadata which we don't need in ingestion
        """
        results = []
        for record in records:
            self._delete_metadata_from_dict(record)
            results.append(self._flatten(record))
        return results

    def _delete_metadata_from_dict(self, json_dict):
        for key in json_dict.keys():
            if key in ["attributes", "totalSize", "done"]:
                json_dict.pop(key)
            elif type(json_dict[key]) == dict:
                self._delete_metadata_from_dict(json_dict[key])
            elif type(json_dict[key]) == list:
                for el in json_dict[key]:
                    self._delete_metadata_from_dict(el)

    def _flatten(self, json_dict, parent_key="", sep="_"):
        """
            Reduce number of dict levels
            Note: useful to bigquery autodetect schema
        """
        items = []
        for k, v in json_dict.items():
            new_key = parent_key + sep + k if parent_key else k
            if isinstance(v, collections.MutableMapping):
                items.extend(self._flatten(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def _request_data(self, endpoint, params=None):
        return requests.get(
            self.format_endpoint(endpoint),
            headers=self.format_headers(),
            params=params,
            timeout=30
        )

    def format_query(self, query):
        return {
            'q': query
        }

    def format_headers(self):
        return {
            'Content-type': 'application/json',
            'Accept-Encoding': 'gzip',
            'Authorization': 'Bearer {}'.format(self._access_token)
        }

    def format_params(self):
        return {
            "grant_type": "password",
            "client_id": self._key,
            "client_secret": self._secret,
            "username": self._user,
            "password": self._password,
            "redirect_uri": self._redirect_uri
        }

    def format_endpoint(self, endpoint):
        formated_url = '{}{}'.format(self._instance_url, endpoint)
        logging.info("Requesting {}".format(formated_url))
        return formated_url
