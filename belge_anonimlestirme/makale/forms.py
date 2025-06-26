from django import forms
from .models import Makale, Kullanici


class MakaleYuklemeForm(forms.ModelForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = Makale
        fields = ['baslik', 'dosya', 'email']
