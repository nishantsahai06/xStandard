"""Test that schema regex patterns are enforced on DM code segments."""
from fault_mapper.adapters.secondary.schema_validator import validate_against_schema
from fault_mapper.domain.models import (
    S1000DFaultDataModule, FaultHeader, FaultContent,
    FaultReportingContent, FaultEntry, FaultDescription, Provenance,
)
from fault_mapper.domain.value_objects import DmCode, Language, IssueInfo, IssueDate, DmTitle
from fault_mapper.domain.enums import FaultMode, FaultEntryType

# DM code with invalid patterns
module = S1000DFaultDataModule(
    record_id="REC-002",
    mode=FaultMode.FAULT_REPORTING,
    header=FaultHeader(
        dm_code=DmCode(
            model_ident_code="bad lowercase",   # violates ^[A-Z0-9]{2,14}$
            system_diff_code="toolong!!",       # violates ^[A-Z0-9]{1,4}$
            system_code="29",
            sub_system_code="0",
            sub_sub_system_code="0",
            assy_code="00",
            disassy_code="00",
            disassy_code_variant="A",
            info_code="031",
            info_code_variant="A",
            item_location_code="A",
        ),
        language=Language(language_iso_code="EN", country_iso_code="us"),  # wrong case
        issue_info=IssueInfo(issue_number="1", in_work="0"),  # too short
        issue_date=IssueDate(year="26", month="13", day="32"),  # bad values
        dm_title=DmTitle(tech_name="OK title"),
    ),
    content=FaultContent(
        warnings_and_cautions=[],
        refs=[],
        fault_reporting=FaultReportingContent(
            fault_entries=[
                FaultEntry(
                    entry_type=FaultEntryType.DETECTED_FAULT,
                    fault_descr=FaultDescription(descr="test"),
                )
            ]
        ),
    ),
    provenance=Provenance(
        source_document_id="DOC-001",
        source_section_ids=["SEC-01"],
    ),
)

issues = validate_against_schema(module)
print(f"{len(issues)} SCHEMA issue(s) from pattern violations:\n")
for i in issues:
    print(f"  [{i.code}] {i.field_path}")
    print(f"    {i.message[:100]}")
    print()
