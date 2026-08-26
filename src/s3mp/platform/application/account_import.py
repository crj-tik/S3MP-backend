"""Safe parsing and validation for platform-account Excel imports."""

import base64
import binascii
import io
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from xml.etree import ElementTree

from s3mp.common.errors import ApiError

MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024
MAX_IMPORT_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_IMPORT_ROWS = 500
_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_HEADERS = {
    "email": "email",
    "邮箱": "email",
    "employee_number": "employee_number",
    "系统号": "employee_number",
    "display_name": "display_name",
    "姓名": "display_name",
    "password": "password",
    "初始密码": "password",
}
_REQUIRED_HEADERS = frozenset(_HEADERS.values())
_EMPLOYEE_NUMBER = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    row: int
    email: str
    normalized_email: str
    employee_number: str
    normalized_employee_number: str
    display_name: str
    password: str


@dataclass(frozen=True, slots=True)
class ImportRowError:
    row: int
    email: str | None
    employee_number: str | None
    code: str
    message: str


def decode_xlsx(filename: str, content_base64: str) -> bytes:
    if not filename.lower().endswith(".xlsx"):
        raise ApiError("validation_failed", "Only .xlsx files are supported", 422)
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ApiError("validation_failed", "Excel file content is invalid", 422) from exc
    if not content or len(content) > MAX_IMPORT_FILE_BYTES:
        raise ApiError("validation_failed", "Excel file must be no larger than 10 MiB", 422)
    return content


def parse_account_import(content: bytes) -> tuple[list[ImportCandidate], list[ImportRowError]]:
    """Read the first worksheet without evaluating formulas or retaining passwords in errors."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ApiError("validation_failed", "The uploaded file is not a valid .xlsx workbook", 422) from exc
    with archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_IMPORT_UNCOMPRESSED_BYTES:
            raise ApiError("validation_failed", "Excel file expands beyond the allowed size", 422)
        shared = _shared_strings(archive)
        rows = list(_worksheet_rows(archive, shared))
    if not rows:
        raise ApiError("validation_failed", "Excel worksheet is empty", 422)
    header_row, headers = rows[0]
    del header_row
    columns = _map_headers(headers)
    candidates: list[ImportCandidate] = []
    errors: list[ImportRowError] = []
    seen_emails: set[str] = set()
    seen_employee_numbers: set[str] = set()
    for row_number, values in rows[1:]:
        if not any(value.strip() for value in values.values()):
            continue
        if len(candidates) + len(errors) >= MAX_IMPORT_ROWS:
            raise ApiError("validation_failed", "Excel file can contain at most 500 data rows", 422)
        raw = {field: values.get(column, "").strip() for field, column in columns.items()}
        email = raw["email"]
        employee_number = raw["employee_number"]
        display_name = raw["display_name"]
        password = raw["password"]
        normalized_email = email.casefold()
        normalized_employee_number = employee_number.casefold()
        error = _validate_row(
            row_number, email, employee_number, display_name, password, normalized_employee_number
        )
        if error is None and (
            normalized_email in seen_emails or normalized_employee_number in seen_employee_numbers
        ):
            error = ImportRowError(
                row_number, email or None, employee_number or None, "duplicate_in_file", "Duplicate email or employee number in this Excel file"
            )
        if error is not None:
            errors.append(error)
            continue
        seen_emails.add(normalized_email)
        seen_employee_numbers.add(normalized_employee_number)
        candidates.append(
            ImportCandidate(
                row=row_number,
                email=email,
                normalized_email=normalized_email,
                employee_number=employee_number,
                normalized_employee_number=normalized_employee_number,
                display_name=display_name,
                password=password,
            )
        )
    return candidates, errors


def _validate_row(
    row: int,
    email: str,
    employee_number: str,
    display_name: str,
    password: str,
    normalized_employee_number: str,
) -> ImportRowError | None:
    if not email or "@" not in email:
        return ImportRowError(row, email or None, employee_number or None, "invalid_email", "Email is invalid")
    if not _EMPLOYEE_NUMBER.fullmatch(normalized_employee_number):
        return ImportRowError(row, email, employee_number or None, "invalid_employee_number", "Employee number format is invalid")
    if not display_name:
        return ImportRowError(row, email, employee_number, "invalid_display_name", "Display name must not be blank")
    if len(password) < 8:
        return ImportRowError(row, email, employee_number, "invalid_password", "Initial password must be at least 8 characters")
    return None


def _map_headers(headers: dict[int, str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for index, header in headers.items():
        field = _HEADERS.get(header.strip().casefold())
        if field is None:
            continue
        if field in columns:
            raise ApiError("validation_failed", f"Duplicate Excel column: {field}", 422)
        columns[field] = index
    missing = _REQUIRED_HEADERS - columns.keys()
    if missing:
        raise ApiError("validation_failed", "Excel must contain 姓名、邮箱、系统号、初始密码 columns", 422)
    return columns


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    # XLSX XML is read locally from the bounded ZIP archive; ElementTree does not fetch externals.
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))  # noqa: S314
    return ["".join(item.itertext()) for item in root.findall(f"{{{_SPREADSHEET_NS}}}si")]


def _worksheet_rows(archive: zipfile.ZipFile, shared: list[str]) -> Iterable[tuple[int, dict[int, str]]]:
    worksheet = next((name for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")), None)
    if worksheet is None:
        raise ApiError("validation_failed", "Excel file has no worksheet", 422)
    # XLSX XML is read locally from the bounded ZIP archive; ElementTree does not fetch externals.
    root = ElementTree.fromstring(archive.read(worksheet))  # noqa: S314
    for row in root.findall(f".//{{{_SPREADSHEET_NS}}}row"):
        row_number = int(row.attrib.get("r", "0"))
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{_SPREADSHEET_NS}}}c"):
            reference = cell.attrib.get("r", "")
            column = _column_index(reference)
            if cell.find(f"{{{_SPREADSHEET_NS}}}f") is not None:
                raise ApiError("validation_failed", "Excel formulas are not supported in imports", 422)
            kind = cell.attrib.get("t")
            if kind == "inlineStr":
                inline = cell.find(f"{{{_SPREADSHEET_NS}}}is")
                values[column] = "" if inline is None else "".join(inline.itertext())
                continue
            value = cell.findtext(f"{{{_SPREADSHEET_NS}}}v") or ""
            if kind == "s":
                try:
                    values[column] = shared[int(value)]
                except (ValueError, IndexError) as exc:
                    raise ApiError("validation_failed", "Excel shared string is invalid", 422) from exc
            else:
                values[column] = value
        yield row_number, values


def _column_index(reference: str) -> int:
    result = 0
    for character in reference:
        if character.isalpha():
            result = result * 26 + ord(character.upper()) - ord("A") + 1
        else:
            break
    return result - 1
