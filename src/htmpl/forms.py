"""
Pydantic-based form handling with HTML5 + server validation.

Usage:
    from pydantic import BaseModel, Field, EmailStr
    from htmpl.forms import BaseForm

    class SignupForm(BaseForm):
        username: str = Field(min_length=3, max_length=20)
        email: EmailStr
        password: str = Field(min_length=8)
        age: int = Field(ge=18, le=120)

    # Render the form
    SignupForm.render(action="/signup")
    SignupForm.render(action="/signup", values=data, errors=errors)
"""

from __future__ import annotations

from typing import Any, Literal,Protocol, TypeVar, cast, get_origin, get_args

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from tdom import Node, html


Choices = list[list[str | int | bool | float]]
Widget = Literal["input", "textarea", "select", "checkbox", "radio", "hidden"]
T = TypeVar("T", bound=BaseModel)


class FormLayout(Protocol):
    """Protocol for custom form layout functions."""

    def __call__(
        self,
        form: type["BaseForm"],
        *,
        values: dict[str, Any],
        errors: dict[str, str],
        submit_text: str,
        form_attrs: dict[str, Any],
    ) -> Node: ...


def default_layout(
    form: type["BaseForm"],
    *,
    values: dict[str, Any],
    errors: dict[str, str],
    submit_text: str,
    form_attrs: dict[str, Any],
) -> Node:
    """Default form layout - renders all fields in order with a submit button."""
    configs = form.get_field_configs()

    fields = [
        form.render_field(name, values.get(name), errors.get(name))
        for name in configs
    ]

    return html(t"""
        <form {form_attrs}>
            {fields}
            <button type="submit">{submit_text}</button>
        </form>
    """)

class FieldConfig(BaseModel):
    """Configuration for how a field should render."""

    name: str
    label: str
    type: str = "text"
    required: bool = False
    placeholder: str = ""
    description: str | None = None
    role: str | None = None

    min: int | float | None = None
    max: int | float | None = None
    minlength: int | None = None
    maxlength: int | None = None
    pattern: str | None = None
    step: int | float | None = None

    choices: Choices | None = None
    rows: int = 4
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

    required = (
        field_info.default is PydanticUndefined and field_info.default_factory is None
    )

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


def _attrs(**kwargs: Any) -> dict[str, Any]:
    """Filter out None/False values, convert True to empty string for boolean attrs."""
    return {
        k.rstrip("_").replace("_", "-"): ("" if v is True else v)
        for k, v in kwargs.items()
        if v is not None and v is not False
    }


class BaseForm(BaseModel):
    """
    Base class for forms that can render themselves.

    Usage:
        class LoginForm(BaseForm):
            email: EmailStr
            password: str = Field(min_length=8)

        LoginForm.render(action="/login", values=values, errors=errors)
    """

    @classmethod
    def get_field_configs(cls) -> dict[str, FieldConfig]:
        """Cache field configurations."""
        if not hasattr(cls, "_field_config_cache"):
            configs = {}
            for name, field_info in cls.model_fields.items():
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
        submit_text: str = "Submit",
        layout: FormLayout | None = None,
        **form_attrs,
    ) -> Node:
        """Render the complete form using the specified layout."""
        form_attrs = _attrs(action=action, method=method, **form_attrs)
        layout_fn = layout or default_layout

        return layout_fn(
            cls,
            values=values or {},
            errors=errors or {},
            submit_text=submit_text,
            form_attrs=form_attrs,
        )

    @classmethod
    def render_field(
        cls,
        name: str,
        value: Any = None,
        error: str | None = None,
    ) -> Node:
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
        **extra_attrs,
    ) -> Node:
        """Render just the input element, no label wrapper."""
        configs = cls.get_field_configs()
        cfg = configs.get(name)
        if not cfg:
            raise ValueError(f"Unknown field: {name}")
        return cls._render_input_only(cfg, value, error, extra_attrs)

    @classmethod
    def label_for(cls, name: str) -> Node:
        """Render just the label element for a field."""
        configs = cls.get_field_configs()
        cfg = configs.get(name)
        if not cfg:
            raise ValueError(f"Unknown field: {name}")
        label_text = cfg.label
        return html(t'<label for="{name}">{label_text}</label>')

    @classmethod
    def error_for(cls, name: str, errors: dict[str, str] | None = None) -> Node | None:
        """Render error message for a field if present."""
        if not errors or name not in errors:
            return None
        msg = errors[name]
        return html(t'<small id="{name}-error" class="error">{msg}</small>')

    @classmethod
    def form_fields(
        cls,
        *names: str,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> list[Node]:
        """Render multiple fields as a list."""
        values = values or {}
        errors = errors or {}
        return [
            cls.render_field(name, values.get(name), errors.get(name)) for name in names
        ]

    @classmethod
    def inline(
        cls,
        *names: str,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> Node:
        """Render fields inline in a grid row."""
        fields = cls.form_fields(*names, values=values, errors=errors)
        return html(t'<div class="grid">{fields}</div>')

    @classmethod
    def group(
        cls,
        title: str,
        *names: str,
        values: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> Node:
        """Render fields in a fieldset with legend."""
        fields = cls.form_fields(*names, values=values, errors=errors)
        return html(t"""
            <fieldset>
                <legend>{title}</legend>
                {fields}
            </fieldset>
        """)

    @classmethod
    def _render_input_only(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Node:
        """Render just the input/select/textarea element."""
        match cfg.widget:
            case "select":
                return cls._render_select_input(cfg, value, error, extra_attrs)
            case "textarea":
                return cls._render_textarea_input(cfg, value, error, extra_attrs)
            case "checkbox":
                return cls._render_checkbox_input(cfg, value, error, extra_attrs)
            case "hidden":
                name, val = cfg.name, str(value or "")
                return html(t'<input type="hidden" name="{name}" value="{val}" />')
            case _:
                return cls._render_input_element(cfg, value, error, extra_attrs)

    @classmethod
    def _render_input_element(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Node:
        """Render an <input> element."""
        attrs = _attrs(
            type=cfg.type,
            name=cfg.name,
            id=cfg.name,
            value=str(value) if value is not None else "",
            placeholder=cfg.placeholder or None,
            required=cfg.required,
            minlength=cfg.minlength,
            maxlength=cfg.maxlength,
            min=cfg.min,
            max=cfg.max,
            pattern=cfg.pattern,
            step=cfg.step,
            aria_invalid="true" if error else None,
            aria_describedby=f"{cfg.name}-error" if error else None,
            **extra_attrs,
        )
        return html(t"<input {attrs} />")

    @classmethod
    def _render_textarea_input(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Node:
        """Render a <textarea> element."""
        attrs = _attrs(
            name=cfg.name,
            id=cfg.name,
            placeholder=cfg.placeholder or None,
            required=cfg.required,
            rows=cfg.rows,
            minlength=cfg.minlength,
            maxlength=cfg.maxlength,
            aria_invalid="true" if error else None,
            **extra_attrs,
        )
        content = value or ""
        return html(t"<textarea {attrs}>{content}</textarea>")

    @classmethod
    def _render_select_input(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Node:
        """Render a <select> element."""
        str_value = str(value) if value is not None else ""
        attrs = _attrs(
            name=cfg.name,
            id=cfg.name,
            required=cfg.required,
            aria_invalid="true" if error else None,
            **extra_attrs,
        )

        options = [
            cls._render_option("", "Select...", selected=not str_value, disabled=True)
        ] + [
            cls._render_option(str(val), str(lbl), selected=(str(val) == str_value))
            for val, lbl in (cfg.choices or [])
        ]

        return html(t"<select {attrs}>{options}</select>")

    @classmethod
    def _render_option(
        cls, value: str, label: str, selected: bool = False, disabled: bool = False
    ) -> Node:
        """Render an <option> element."""
        attrs = _attrs(value=value, selected=selected, disabled=disabled)
        return html(t"<option {attrs}>{label}</option>")

    @classmethod
    def _render_checkbox_input(
        cls,
        cfg: FieldConfig,
        value: Any,
        error: str | None,
        extra_attrs: dict[str, Any],
    ) -> Node:
        """Render a checkbox <input> element."""
        attrs = _attrs(
            type="checkbox",
            name=cfg.name,
            id=cfg.name,
            checked=bool(value),
            required=cfg.required,
            role=cfg.role,
            **extra_attrs,
        )
        return html(t"<input {attrs} />")

    @classmethod
    def _render_field(cls, cfg: FieldConfig, value: Any, error: str | None) -> Node:
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
                name, val = cfg.name, str(value or "")
                return html(t'<input type="hidden" name="{name}" value="{val}" />')
            case _:
                return cls._render_input(cfg, value, error)

    @classmethod
    def _render_hint(cls, cfg: FieldConfig, error: str | None) -> Node | None:
        """Render description or error hint."""
        if error:
            return html(t'<small class="error">{error}</small>')
        if cfg.description:
            desc = cfg.description
            return html(t"<small>{desc}</small>")
        return None

    @classmethod
    def _render_input(cls, cfg: FieldConfig, value: Any, error: str | None) -> Node:
        """Render a labeled input field."""
        label_text = cfg.label
        input_el = cls._render_input_element(cfg, value, error, {})
        hint = cls._render_hint(cfg, error)
        return html(t"<label>{label_text}{input_el}{hint}</label>")

    @classmethod
    def _render_textarea(cls, cfg: FieldConfig, value: Any, error: str | None) -> Node:
        """Render a labeled textarea field."""
        label_text = cfg.label
        textarea_el = cls._render_textarea_input(cfg, value, error, {})
        hint = cls._render_hint(cfg, error)
        return html(t"<label>{label_text}{textarea_el}{hint}</label>")

    @classmethod
    def _render_select(cls, cfg: FieldConfig, value: Any, error: str | None) -> Node:
        """Render a labeled select field."""
        label_text = cfg.label
        select_el = cls._render_select_input(cfg, value, error, {})
        hint = cls._render_hint(cfg, error)
        return html(t"<label>{label_text}{select_el}{hint}</label>")

    @classmethod
    def _render_checkbox(cls, cfg: FieldConfig, value: Any, error: str | None) -> Node:
        """Render a labeled checkbox field."""
        label_text = cfg.label
        checkbox_el = cls._render_checkbox_input(cfg, value, error, {})
        hint = cls._render_hint(cfg, error)
        return html(t"<label>{checkbox_el}{label_text}{hint}</label>")

    @classmethod
    def _render_radio(cls, cfg: FieldConfig, value: Any, error: str | None) -> Node:
        """Render a radio group in a fieldset."""
        str_value = str(value) if value is not None else ""
        label_text = cfg.label
        hint = cls._render_hint(cfg, error)

        radios = [
            cls._render_radio_option(cfg.name, str(val), str(lbl), str(val) == str_value, cfg.required)
            for val, lbl in (cfg.choices or [])
        ]

        return html(t"""
            <fieldset>
                <legend>{label_text}</legend>
                {radios}
                {hint}
            </fieldset>
        """)

    @classmethod
    def _render_radio_option(
        cls, name: str, value: str, label: str, checked: bool, required: bool
    ) -> Node:
        """Render a single radio option."""
        input_id = f"{name}_{value}"
        attrs = _attrs(
            type="radio",
            name=name,
            id=input_id,
            value=value,
            checked=checked,
            required=required,
        )
        return html(t"<label><input {attrs} />{label}</label>")


def parse_form_errors(error: ValidationError) -> dict[str, str]:
    """Convert Pydantic ValidationError to field -> message dict."""
    errors = {}
    for err in error.errors():
        loc = err["loc"]
        if loc:
            field = str(loc[0])
            errors[field] = err["msg"]
    return errors
