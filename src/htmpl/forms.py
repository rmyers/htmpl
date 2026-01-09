"""
Pydantic-based form handling with HTML5 + server validation.

Usage:
    from pydantic import BaseModel, Field, EmailStr
    from htmpl.forms import FormRenderer

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

from typing import Any, Literal, TypeVar, cast, get_origin, get_args

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from .elements import (
    Element,
    button,
    div,
    fieldset,
    form,
    input_,
    label,
    legend,
    option,
    select,
    small,
    textarea,
)


# Choices can be list of [value, label] pairs
Choices = list[list[str | int | bool | float]]
Widget = Literal["input", "textarea", "select", "checkbox", "radio", "hidden"]
T = TypeVar("T", bound=BaseModel)


class FieldConfig(BaseModel):
    """Configuration for how a field should render."""

    name: str
    label: str
    type: str = "text"
    required: bool = False
    placeholder: str = ""
    description: str | None = None
    role: str | None = None

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


def _extract_field_config(name: str, annotation: type, field_info: FieldInfo) -> FieldConfig:
    """Extract FieldConfig from Pydantic field."""
    origin = get_origin(annotation)
    if origin is type(None) or str(origin) == "typing.Union":
        args = get_args(annotation)
        annotation = args[0] if args else str

    choices: Choices | None = None
    if origin is Literal:
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

    required = field_info.default is PydanticUndefined and field_info.default_factory is None

    placeholder: str = ""
    if field_info.examples:
        placeholder = ", ".join([str(e) for e in field_info.examples])

    return FieldConfig(
        name=name,
        label=field_info.title or _label_from_name(name),
        type=input_type,
        required=required,
        placeholder=placeholder,
        description=field_info.description,
        choices=choices,
        widget=widget,
        **metadata,
    )


class BaseForm(BaseModel):
    """
    Base class for forms that can render themselves.

    Usage:
        class LoginSchema(BaseForm):
            email: EmailStr
            password: str = Field(min_length=8)

        # Render the form (class method)
        LoginSchema.render(action="/login", values=values, errors=errors)

        # Validate and create instance (normal Pydantic)
        data = LoginSchema(**form_data)
    """

    @classmethod
    def get_field_configs(cls) -> dict[str, FieldConfig]:
        """Cache field configurations."""
        if not hasattr(cls, "_field_config_cache"):
            configs = {}
            for name, field_info in cls.model_fields.items():
                # Use the annotation stored by Pydantic
                annotation = field_info.annotation or str
                configs[name] = _extract_field_config(name, annotation, field_info)
            cls._field_config_cache = configs
        return cls._field_config_cache

    @classmethod
    def configure_field(cls, name: str, **kwargs) -> type["BaseForm"]:
        """Override configuration for a specific field."""
        configs = cls.get_field_configs()
        if name in configs:
            for key, value in kwargs.items():
                setattr(configs[name], key, value)
        return cls

    @classmethod
    def render(
        cls,
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
        configs = cls.get_field_configs()

        if include:
            field_names = [n for n in include if n in configs]
        else:
            field_names = [n for n in configs if n not in exclude]

        fields = [
            cls._render_field(configs[name], values.get(name), errors.get(name))
            for name in field_names
        ]

        return form(
            *fields,
            button(submit_text, type="submit"),
            action=action,
            method=method,
            **form_attrs,
        )

    @classmethod
    def render_field(
        cls,
        name: str,
        value: Any = None,
        error: str | None = None,
    ) -> Element:
        """Render a single field with label wrapper."""
        configs = cls.get_field_configs()
        cfg = configs.get(name)
        if not cfg:
            raise ValueError(f"Unknown field: {name}")
        return cls._render_field(cfg, value, error)

    @classmethod
    def input(
        cls,
        name: str,
        value: Any = None,
        error: str | None = None,
        **attrs,
    ) -> Element:
        """Render just the input element, no label wrapper."""
        configs = cls.get_field_configs()
        cfg = configs.get(name)
        if not cfg:
            raise ValueError(f"Unknown field: {name}")
        return cls._render_input_only(cfg, value, error, attrs)

    @classmethod
    def label_for(cls, name: str) -> Element:
        """Render just the label element for a field."""
        configs = cls.get_field_configs()
        cfg = configs.get(name)
        if not cfg:
            raise ValueError(f"Unknown field: {name}")
        return label(cfg.label, for_=name)

    @classmethod
    def error_for(cls, name: str, errors: dict[str, str] | None = None) -> Element | None:
        """Render error message for a field if present."""
        if not errors or name not in errors:
            return None
        return small(errors[name], id=f"{name}-error", class_="error")

    @classmethod
    def fields(
        cls,
        *names: str,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> list[Element]:
        """Render multiple fields as a list."""
        values = values or {}
        errors = errors or {}
        return [cls.render_field(name, values.get(name), errors.get(name)) for name in names]

    @classmethod
    def inline(
        cls,
        *names: str,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> Element:
        """Render fields inline in a grid row."""
        return div(
            cls.fields(*names, values=values, errors=errors),
            class_="grid",
        )

    @classmethod
    def group(
        cls,
        title: str,
        *names: str,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> Element:
        """Render fields in a fieldset with legend."""
        return fieldset(
            legend(title),
            *cls.fields(*names, values=values, errors=errors),
        )

    @classmethod
    def _render_input_only(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Element:
        """Render just the input/select/textarea element."""
        match cfg.widget:
            case "select":
                return cls._render_select_input(cfg, value, error, extra_attrs)
            case "textarea":
                return cls._render_textarea_input(cfg, value, error, extra_attrs)
            case "checkbox":
                return cls._render_checkbox_input(cfg, value, error, extra_attrs)
            case "hidden":
                return input_(type="hidden", name=cfg.name, value=str(value or ""), **extra_attrs)
            case _:
                return cls._render_input_element(cfg, value, error, extra_attrs)

    @classmethod
    def _render_input_element(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Element:
        """Render an <input> element."""
        attrs: dict[str, Any] = {
            "type": cfg.type,
            "name": cfg.name,
            "id": cfg.name,
            "value": str(value) if value is not None else "",
            "placeholder": cfg.placeholder or None,
            "required": cfg.required or None,
            "minlength": str(cfg.minlength) if cfg.minlength else None,
            "maxlength": str(cfg.maxlength) if cfg.maxlength else None,
            "min": str(cfg.min) if cfg.min is not None else None,
            "max": str(cfg.max) if cfg.max is not None else None,
            "pattern": cfg.pattern,
            "step": str(cfg.step) if cfg.step else None,
            **extra_attrs,
        }
        if error:
            attrs["aria-invalid"] = "true"
            attrs["aria-describedby"] = f"{cfg.name}-error"
        return input_(**{k: v for k, v in attrs.items() if v is not None})

    @classmethod
    def _render_textarea_input(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Element:
        """Render a <textarea> element."""
        attrs: dict[str, Any] = {
            "name": cfg.name,
            "id": cfg.name,
            "placeholder": cfg.placeholder or None,
            "required": cfg.required or None,
            "rows": str(cfg.rows),
            "minlength": str(cfg.minlength) if cfg.minlength else None,
            "maxlength": str(cfg.maxlength) if cfg.maxlength else None,
            **extra_attrs,
        }
        if error:
            attrs["aria-invalid"] = "true"
        return textarea(str(value or ""), **{k: v for k, v in attrs.items() if v is not None})

    @classmethod
    def _render_select_input(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Element:
        """Render a <select> element."""
        str_value = str(value) if value is not None else ""
        options = [
            option(lbl, value=val, selected=(val == str_value) or None)
            for val, lbl in (cfg.choices or [])
        ]
        attrs: dict[str, Any] = {
            "name": cfg.name,
            "id": cfg.name,
            "required": cfg.required or None,
            **extra_attrs,
        }
        if error:
            attrs["aria-invalid"] = "true"
        return select(
            option("Select...", value="", disabled=True, selected=(not str_value) or None),
            *options,
            **{k: v for k, v in attrs.items() if v is not None},
        )

    @classmethod
    def _render_checkbox_input(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Element:
        """Render a checkbox <input> element."""
        return input_(
            type="checkbox",
            name=cfg.name,
            id=cfg.name,
            checked=bool(value) or None,
            required=cfg.required or None,
            role=cfg.role or None,
            **extra_attrs,
        )

    @classmethod
    def _render_field(cls, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        """Render a field based on its configuration."""
        match cfg.widget:
            case "select":
                return cls._render_select(cfg, value, error)
            case "textarea":
                return cls._render_textarea(cfg, value, error)
            case "checkbox":
                return cls._render_checkbox(cfg, value, error)
            case "radio":
                return cls._render_radio(cfg, value, error)
            case "hidden":
                return input_(type="hidden", name=cfg.name, value=str(value or ""))
            case _:
                return cls._render_input(cfg, value, error)

    @classmethod
    def _render_input(cls, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        return label(
            cfg.label,
            cls._render_input_element(cfg, value, error, {}),
            small(cfg.description) if cfg.description and not error else None,
            small(error, id=f"{cfg.name}-error", class_="error") if error else None,
        )

    @classmethod
    def _render_textarea(cls, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        return label(
            cfg.label,
            cls._render_textarea_input(cfg, value, error, {}),
            small(cfg.description) if cfg.description and not error else None,
            small(error, class_="error") if error else None,
        )

    @classmethod
    def _render_select(cls, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        return label(
            cfg.label,
            cls._render_select_input(cfg, value, error, {}),
            small(cfg.description) if cfg.description and not error else None,
            small(error, class_="error") if error else None,
        )

    @classmethod
    def _render_checkbox(cls, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        return label(
            cls._render_checkbox_input(cfg, value, error, {}),
            cfg.label,
            small(cfg.description) if cfg.description and not error else None,
            small(error, class_="error") if error else None,
        )

    @classmethod
    def _render_radio(cls, cfg: FieldConfig, value: Any, error: str | None) -> Element:
        str_value = str(value) if value is not None else ""
        radios = [
            label(
                input_(
                    type="radio",
                    name=cfg.name,
                    id=f"{cfg.name}_{val}",
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
            small(cfg.description) if cfg.description and not error else None,
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
