# GNU Lesser General Public License v3.0 only
# Copyright (C) 2020 Artefact
# licence-information@artefact.com
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
from nck.writers.writer import Writer

from nck.writers.gcs_writer import gcs
from nck.writers.console_writer import console
from nck.writers.local_writer import local
from nck.writers.bigquery_writer import bq
from nck.writers.s3_writer import s3


writers = [
    gcs,
    console,
    local,
    bq,
    s3
    # "oracle": oracle,
    # "gsheets": gsheets,
    # "salesforce": salesforce
]

__all__ = ["writers", "Writer"]
