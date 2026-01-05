"""
Pydantic-based form handling with HTML5 + server validation.

Usage:
    from pydantic import BaseModel, Field, EmailStr
    from thtml.forms import FormRenderer

    class SignupSchema(BaseModel):
        username: str = Field(min_length=3, max_length=20)
        email: EmailStr
        password: str = Field(min_length=8)
        age: int = Field(ge=18, le=120)

    form = FormRenderer(SignupSchema)
    form.render(action="/signup")
    form.render(action="/signup", values=data, errors=errors)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Literal, cast, get_origin, get_args

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from .elements import (
    Element,
    form,
    label,
    input_,
    select,
    option,
    textarea,
    button,
    small,
    fieldset,
    legend,
)


# Choices can be list of [value, label] pairs
Choices = list[list[str | int | bool | float]]
Widget = Literal["input", "textarea", "select", "checkbox", "radio", "hidden"]


class FieldConfig(BaseModel):
    """Configuration for how a field should render."""

    name: str
    label: str
    type: str = "text"
    required: bool = False
    placeholder: str = ""

    # HTML5 validation attributes
    min: int | float | None = None
    max: int | float | None = None
    minlength: int | None = None
    maxlength: int | None = None
    pattern: str | None = None
    step: int | float | None = None

    # Select/radio options: [[value, label], ...]
    choices: Choices | None = None

    # Textarea
    rows: int = 4

    # Widget override
    widget: Widget | None = None


def _label_from_name(name: str) -> str:
    """Convert field_name to Field Name."""
    return name.replace("_", " ").title()


def _infer_input_type(python_type: type, field_name: str) -> str:
    """Infer HTML input type from Python type and field name."""
    type_str = str(python_type)

    if python_type is int:
        return "number"
    if python_type is float:
        return "number"
    if python_type is bool:
        return "checkbox"
    if "EmailStr" in type_str:
        return "email"
    if "HttpUrl" in type_str or "AnyUrl" in type_str:
        return "url"
    if "SecretStr" in type_str:
        return "password"

    name_lower = field_name.lower()
    if "password" in name_lower:
        return "password"
    if "email" in name_lower:
        return "email"
    if "url" in name_lower or "website" in name_lower:
        return "url"
    if "phone" in name_lower or "tel" in name_lower:
        return "tel"
    if "date" in name_lower and "time" not in name_lower:
        return "date"
    if "time" in name_lower and "date" not in name_lower:
        return "time"
    if "datetime" in name_lower:
        return "datetime-local"
    if "color" in name_lower:
        return "color"

    return "text"


def _extract_field_config(
    name: str, annotation: type, field_info: FieldInfo
) -> FieldConfig:
    """Extract FieldConfig from Pydantic field."""
    origin = get_origin(annotation)
    if origin is type(None) or str(origin) == "typing.Union":
        args = get_args(annotation)
        annotation = args[0] if args else str

    choices: Choices | None = None
    print(origin)
    if origin is Literal:
        print("I am literally here")
        args = get_args(annotation)
        choices = [[str(a), str(a)] for a in args]

    metadata = {}
    if field_info.metadata:
        for m in field_info.metadata:
            if hasattr(m, "min_length"):
                metadata["minlength"] = m.min_length
            if hasattr(m, "max_length"):
                metadata["maxlength"] = m.max_length
            if hasattr(m, "ge"):
                metadata["min"] = m.ge
            if hasattr(m, "gt"):
                metadata["min"] = m.gt + 1
            if hasattr(m, "le"):
                metadata["max"] = m.le
            if hasattr(m, "lt"):
                metadata["max"] = m.lt - 1
            if hasattr(m, "pattern"):
                metadata["pattern"] = m.pattern

    widget = "input"
    extra = field_info.json_schema_extra or {}
    if isinstance(extra, dict):
        widget = cast(Widget, extra.get("form_widget", widget))
        if raw_choices := extra.get("form_choices", None):
            choices = cast(Choices, raw_choices)
        metadata = {**metadata, **extra}

    if choices and widget == "input":
        widget = "select"

    input_type = _infer_input_type(annotation, name)
    if input_type == "checkbox":
        widget = "checkbox"

    required = (
        field_info.default is PydanticUndefined and field_info.default_factory is None
    )

    return FieldConfig(
        name=name,
        label=field_info.title or _label_from_name(name),
        type=input_type,
        required=required,
        placeholder=field_info.description or "",
        choices=choices,
        widget=widget,
        **metadata,
    )


@dataclass
class FormRenderer:
    """Renders Pydantic models as HTML forms."""

    model: type[BaseModel]
    field_configs: dict[str, FieldConfig] = dataclass_field(default_factory=dict)

    def __post_init__(self):
        for name, field_info in self.model.model_fields.items():
            annotation = self.model.__annotations__.get(name, str)
            self.field_configs[name] = _extract_field_config(
                name, annotation, field_info
            )

    def configure(self, name: str, **kwargs) -> "FormRenderer":
        """Override configuration for a specific field."""
        if name in self.field_configs:
            for key, value in kwargs.items():
                setattr(self.field_configs[name], key, value)
        return self

    def render(
        self,
        action: str = "",
        method: str = "post",
        *,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        exclude: set[str] | None = None,
        include: list[str] | None = None,
        submit_text: str = "Submit",
        **form_attrs,
    ) -> Element:
        """Render the complete form."""
        values = values or {}
        errors = errors or {}
        exclude = exclude or set()

        if include:
            field_names = [n for n in include if n in self.field_configs]
        else:
            field_names = [n for n in self.field_configs if n not in exclude]

        fields = [
            self._render_field(
                self.field_configs[name],
                values.get(name),
                errors.get(name),
            )
            for name in field_names
        ]

        return form(
            *fields,
            button(submit_text, type="submit"),
            action=action,
            method=method,
            **form_attrs,
        )

    def render_field(
        self,
        name: str,
        value: Any = None,
        error: str | None = None,
    ) -> Element:
        """Render a single field by name."""
        cfg = self.field_configs.get(name)
        if not cfg:
            raise ValueError(f"Unknown field: {name}")
        return self._render_field(cfg, value, error)

    def _render_field(self, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        """Render a field based on its configuration."""
        match cfg.widget:
            case "select":
                return self._render_select(cfg, value, error)
            case "textarea":
                return self._render_textarea(cfg, value, error)
            case "checkbox":
                return self._render_checkbox(cfg, value, error)
            case "radio":
                return self._render_radio(cfg, value, error)
            case "hidden":
                return input_(type="hidden", name=cfg.name, value=str(value or ""))
            case _:
                return self._render_input(cfg, value, error)

    def _render_input(self, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        attrs: dict[str, Any] = {
            "type": cfg.type,
            "name": cfg.name,
            "value": str(value) if value is not None else "",
            "placeholder": cfg.placeholder or None,
            "required": cfg.required or None,
            "minlength": str(cfg.minlength) if cfg.minlength else None,
            "maxlength": str(cfg.maxlength) if cfg.maxlength else None,
            "min": str(cfg.min) if cfg.min is not None else None,
            "max": str(cfg.max) if cfg.max is not None else None,
            "pattern": cfg.pattern,
            "step": str(cfg.step) if cfg.step else None,
        }

        if error:
            attrs["aria-invalid"] = "true"
            attrs["aria-describedby"] = f"{cfg.name}-error"

        # Filter None values
        attrs = {k: v for k, v in attrs.items() if v is not None}

        return label(
            cfg.label,
            input_(**attrs),
            small(error, id=f"{cfg.name}-error", class_="error") if error else None,
        )

    def _render_textarea(
        self, cfg: FieldConfig, value: Any, error: str | None
    ) -> Element:
        attrs: dict[str, Any] = {
            "name": cfg.name,
            "placeholder": cfg.placeholder or None,
            "required": cfg.required or None,
            "rows": str(cfg.rows),
            "minlength": str(cfg.minlength) if cfg.minlength else None,
            "maxlength": str(cfg.maxlength) if cfg.maxlength else None,
        }
        if error:
            attrs["aria-invalid"] = "true"

        attrs = {k: v for k, v in attrs.items() if v is not None}

        return label(
            cfg.label,
            textarea(str(value or ""), **attrs),
            small(error, class_="error") if error else None,
        )

    def _render_select(
        self, cfg: FieldConfig, value: Any, error: str | None
    ) -> Element:
        str_value = str(value) if value is not None else ""
        options = [
            option(lbl, value=val, selected=(val == str_value) or None)
            for val, lbl in (cfg.choices or [])
        ]

        attrs: dict[str, Any] = {"name": cfg.name, "required": cfg.required or None}
        if error:
            attrs["aria-invalid"] = "true"

        attrs = {k: v for k, v in attrs.items() if v is not None}

        return label(
            cfg.label,
            select(
                option(
                    "Select...",
                    value="",
                    disabled=True,
                    selected=(not str_value) or None,
                ),
                *options,
                **attrs,
            ),
            small(error, class_="error") if error else None,
        )

    def _render_checkbox(
        self, cfg: FieldConfig, value: Any, error: str | None
    ) -> Element:
        return label(
            input_(
                type="checkbox",
                name=cfg.name,
                checked=bool(value) or None,
                required=cfg.required or None,
            ),
            cfg.label,
            small(error, class_="error") if error else None,
        )

    def _render_radio(self, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        str_value = str(value) if value is not None else ""
        radios = [
            label(
                input_(
                    type="radio",
                    name=cfg.name,
                    value=val,
                    checked=(val == str_value) or None,
                    required=cfg.required or None,
                ),
                lbl,
            )
            for val, lbl in (cfg.choices or [])
        ]
        return fieldset(
            legend(cfg.label),
            *radios,
            small(error, class_="error") if error else None,
        )


def parse_form_errors(error: ValidationError) -> dict[str, str]:
    """Convert Pydantic ValidationError to field -> message dict."""
    errors = {}
    for err in error.errors():
        loc = err["loc"]
        if loc:
            field = str(loc[0])
            errors[field] = err["msg"]
    return errors
