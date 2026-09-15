from django import forms

from .models import Device
class SSHCommandForm(forms.Form):
    """Select a managed device and submit one audited Cisco command line."""

    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),  # Filled when the form is created.
        empty_label=None,  # Always require a device selection.
    )
    command = forms.CharField(
        label="Cisco command",
        max_length=200,  # Matches the command field in the audit model.
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. show ip interface brief",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only equipment that can accept IOS commands belongs in the dropdown.
        self.fields["device"].queryset = Device.objects.filter(
            is_enabled=True,  # Hide devices that monitoring has disabled.
            device_type__in=(Device.DeviceType.ROUTER, Device.DeviceType.SWITCH),
        )
