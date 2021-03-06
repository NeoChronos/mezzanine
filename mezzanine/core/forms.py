
from uuid import uuid4

from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.core.validators import validate_email, ValidationError
from django import forms
from django.forms.extras.widgets import SelectDateWidget
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from mezzanine.conf import settings
from mezzanine.core.models import Orderable


class TinyMceWidget(forms.Textarea):
    """
    Setup the JS files and targetting CSS class for a textarea to
    use TinyMCE.
    """

    class Media:
        js = (settings.ADMIN_MEDIA_PREFIX +
              "tinymce/jscripts/tiny_mce/tiny_mce.js",
              settings.TINYMCE_SETUP_JS,)

    def __init__(self, *args, **kwargs):
        super(TinyMceWidget, self).__init__(*args, **kwargs)
        self.attrs["class"] = "mceEditor"


class UserForm(forms.Form):
    """
    Fields for signup & login.
    """
    email = forms.EmailField(label=_("Email Address"))
    password = forms.CharField(label=_("Password"),
                               widget=forms.PasswordInput(render_value=False))

    def __init__(self, request, *args, **kwargs):
        """
        Try and pre-populate the email field with a cookie value.
        """
        initial = {}
        for value in request.COOKIES.values():
            try:
                validate_email(value)
            except ValidationError:
                pass
            else:
                initial["email"] = value
                break
        super(UserForm, self).__init__(initial=initial, *args, **kwargs)

    def authenticate(self):
        """
        Validate email and password as well as setting the user for login.
        """
        self._user = authenticate(username=self.cleaned_data.get("email", ""),
                               password=self.cleaned_data.get("password", ""))

    def login(self, request):
        """
        Log the user in.
        """
        login(request, self._user)


class SignupForm(UserForm):

    def clean_email(self):
        """
        Ensure the email address is not already registered.
        """
        email = self.cleaned_data["email"]
        try:
            User.objects.get(username=email)
        except User.DoesNotExist:
            return email
        raise forms.ValidationError(_("This email is already registered"))

    def save(self):
        """
        Create the new user using their email address as their username.
        """
        user = User.objects.create_user(self.cleaned_data["email"],
                                        self.cleaned_data["email"],
                                        self.cleaned_data["password"])
        settings.use_editable()
        if settings.ACCOUNTS_VERIFICATION_REQUIRED:
            user.is_active = False
            user.save()
        else:
            self.authenticate()
        return user


class LoginForm(UserForm):

    def clean(self):
        """
        Authenticate the email/password.
        """
        if "email" in self.cleaned_data and "password" in self.cleaned_data:
            self.authenticate()
            if self._user is None:
                raise forms.ValidationError(_("Invalid email/password"))
            elif not self._user.is_active:
                raise forms.ValidationError(_("Your account is inactive"))
        return self.cleaned_data


class OrderWidget(forms.HiddenInput):
    """
    Add up and down arrows for ordering controls next to a hidden
    form field.
    """
    def render(self, *args, **kwargs):
        rendered = super(OrderWidget, self).render(*args, **kwargs)
        arrows = ["<img src='%simg/admin/arrow-%s.gif' />" %
            (settings.ADMIN_MEDIA_PREFIX, arrow) for arrow in ("up", "down")]
        arrows = "<span class='ordering'>%s</span>" % "".join(arrows)
        return rendered + mark_safe(arrows)


class DynamicInlineAdminForm(forms.ModelForm):
    """
    Form for ``DynamicInlineAdmin`` that can be collapsed and sorted
    with drag and drop using ``OrderWidget``.
    """

    class Media:
        js = ("mezzanine/js/jquery-ui-1.8.14.custom.min.js",
              "mezzanine/js/admin/dynamic_inline.js",)

    def __init__(self, *args, **kwargs):
        super(DynamicInlineAdminForm, self).__init__(*args, **kwargs)
        if issubclass(self._meta.model, Orderable):
            self.fields["_order"] = forms.CharField(label=_("Order"),
                widget=OrderWidget, required=False)


class SplitSelectDateTimeWidget(forms.SplitDateTimeWidget):
    """
    Combines Django's ``SelectDateTimeWidget`` and ``SelectDateWidget``.
    """
    def __init__(self, attrs=None, date_format=None, time_format=None):
        date_widget = SelectDateWidget(attrs=attrs)
        time_widget = forms.TimeInput(attrs=attrs, format=time_format)
        forms.MultiWidget.__init__(self, (date_widget, time_widget), attrs)


def get_edit_form(obj, field_names, data=None, files=None):
    """
    Returns the in-line editing form for editing a single model field.
    """

    # Map these form fields to their types defined in the forms app so
    # we can make use of their custom widgets.
    from mezzanine.forms import fields
    widget_overrides = {
        forms.DateField: fields.DATE,
        forms.DateTimeField: fields.DATE_TIME,
        forms.EmailField: fields.EMAIL,
    }

    class EditForm(forms.ModelForm):
        """
        In-line editing form for editing a single model field.
        """

        app = forms.CharField(widget=forms.HiddenInput)
        model = forms.CharField(widget=forms.HiddenInput)
        id = forms.CharField(widget=forms.HiddenInput)
        fields = forms.CharField(widget=forms.HiddenInput)

        class Meta:
            model = obj.__class__
            fields = field_names.split(",")

        def __init__(self, *args, **kwargs):
            super(EditForm, self).__init__(*args, **kwargs)
            self.uuid = str(uuid4())
            for f in self.fields.keys():
                field_class = self.fields[f].__class__
                try:
                    field_type = widget_overrides[field_class]
                except KeyError:
                    pass
                else:
                    self.fields[f].widget = fields.WIDGETS[field_type]()
                css_class = self.fields[f].widget.attrs.get("class", "")
                css_class += " " + field_class.__name__.lower()
                self.fields[f].widget.attrs["class"] = css_class
                self.fields[f].widget.attrs["id"] = "%s-%s" % (f, self.uuid)
                if settings.FORMS_USE_HTML5 and self.fields[f].required:
                    self.fields[f].widget.attrs["required"] = ""

    initial = {"app": obj._meta.app_label, "id": obj.id,
               "fields": field_names, "model": obj._meta.object_name.lower()}
    return EditForm(instance=obj, initial=initial, data=data, files=files)
