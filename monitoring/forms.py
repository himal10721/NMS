from django import forms

from .models import Device
class SSHCommandForm(forms.Form):
    """Select a managed device and submit one audited Cisco command line."""

    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        empty_label=None,
    )
    command = forms.CharField(
        label="Cisco command",
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. show ip interface brief",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["device"].queryset = Device.objects.filter(
            is_enabled=True,
            device_type__in=(Device.DeviceType.ROUTER, Device.DeviceType.SWITCH),
        )
