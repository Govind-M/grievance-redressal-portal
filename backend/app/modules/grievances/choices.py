"""Controlled values shared by API validation and future structured AI outputs."""

from enum import StrEnum
from typing import Annotated, TypeVar

from pydantic import BeforeValidator


class District(StrEnum):
    THIRUVANANTHAPURAM = "Thiruvananthapuram"
    KOLLAM = "Kollam"
    PATHANAMTHITTA = "Pathanamthitta"
    ALAPPUZHA = "Alappuzha"
    KOTTAYAM = "Kottayam"
    IDUKKI = "Idukki"
    ERNAKULAM = "Ernakulam"
    THRISSUR = "Thrissur"
    PALAKKAD = "Palakkad"
    MALAPPURAM = "Malappuram"
    KOZHIKODE = "Kozhikode"
    WAYANAD = "Wayanad"
    KANNUR = "Kannur"
    KASARAGOD = "Kasaragod"


class Category(StrEnum):
    ROADS_AND_INFRASTRUCTURE = "Roads and Infrastructure"
    HEALTHCARE = "Healthcare"
    EDUCATION = "Education"
    WATER_SUPPLY = "Water Supply"
    SANITATION_AND_WASTE_MANAGEMENT = "Sanitation and Waste Management"
    ELECTRICITY = "Electricity"
    TRANSPORTATION = "Transportation"
    REVENUE_AND_LAND = "Revenue and Land"
    LOCAL_GOVERNMENT_SERVICES = "Local Government Services"
    PUBLIC_SAFETY = "Public Safety"
    SOCIAL_WELFARE = "Social Welfare"
    OTHER = "Other"


Choice = TypeVar("Choice", bound=StrEnum)


def normalize_choice(value: object, choices: type[Choice]) -> Choice:
    if isinstance(value, str):
        normalized = " ".join(value.split()).casefold()
        for choice in choices:
            if normalized == choice.value.casefold():
                return choice
    raise ValueError(f"Choose a supported {choices.__name__.lower()}")


def normalize_district(value: object) -> District:
    return normalize_choice(value, District)


def normalize_category(value: object) -> Category:
    return normalize_choice(value, Category)


DistrictInput = Annotated[District, BeforeValidator(normalize_district)]
CategoryInput = Annotated[Category, BeforeValidator(normalize_category)]
