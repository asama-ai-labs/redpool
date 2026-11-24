# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register LogService + LogEntry normalizers under Managers/."""

from ..._shared.log_entry.dell import DellLogEntryNormalizer
from ..._shared.log_entry.hpe import HPELogEntryNormalizer
from ..._shared.log_entry.lenovo import LenovoLogEntryNormalizer
from ..._shared.log_services import (
    LOG_ENTRY_COLLECTION,
    LOG_SERVICE_COLLECTION,
    BaseLogEntryNormalizer,
    BaseLogServiceNormalizer,
)
from ..._shared.log_services_dell import DELL_LOG_ENTRY_COLLECTION
from ...registry import (
    register_base,
    register_collection,
    register_collection_override,
    register_resource,
)

register_base("Managers/LogServices", BaseLogServiceNormalizer())
register_collection("Managers/LogServices", LOG_SERVICE_COLLECTION)
register_base("Managers/LogServices/Entries", BaseLogEntryNormalizer())
register_resource("Managers/LogServices/Entries", "Dell", DellLogEntryNormalizer())
register_resource("Managers/LogServices/Entries", "HPE", HPELogEntryNormalizer())
register_resource("Managers/LogServices/Entries", "Lenovo", LenovoLogEntryNormalizer())
register_collection("Managers/LogServices/Entries", LOG_ENTRY_COLLECTION)
register_collection_override(
    "Managers/LogServices/Entries", "Dell", DELL_LOG_ENTRY_COLLECTION
)
