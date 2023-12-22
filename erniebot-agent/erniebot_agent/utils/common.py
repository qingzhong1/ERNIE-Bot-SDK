# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import base64
import mimetypes
import os
from enum import Enum
from typing import List, Union

import requests


def get_cache_dir():
    """Use ~/.cache/erniebot_agent as the cache directory"""
    home_dir = os.path.expanduser("~")
    cache_dir = os.path.join(home_dir, ".cache", "erniebot_agent")
    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)
    return cache_dir


def download_file(url: str, save_path: str):
    """Download file from url"""
    response = requests.get(url)
    assert response.status_code == 200, f"Download file failed: {url}."
    with open(save_path, "wb") as file:
        file.write(response.content)


def create_enum_class(class_name: str, member_names: List[Union[int, str]]):
    """create Enum Class dynamic from openapi.yaml"""
    return Enum(class_name, {name: name for name in member_names})


def get_file_suffix(mime_type: str):
    mapping = {"audio/mp3": "audio/mpeg"}
    mime_type = mapping.get(mime_type, mime_type)
    mime_type_to_suffix = {value: key for key, value in mimetypes.types_map.items()}
    return mime_type_to_suffix.get(mime_type, None)


def is_json_response(response) -> bool:
    try:
        response.json()
        return True
    except Exception:
        return False


def is_base64_string(string: str) -> bool:
    try:
        return base64.b64encode(base64.b64decode(string)) == string
    except Exception:
        return False