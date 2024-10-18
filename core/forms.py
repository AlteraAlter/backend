from django.forms import ModelForm
from django import forms
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from django.contrib.auth.models import User


class RegisterForm(UserCreationForm):
    
    first_name = forms.CharField(
        max_length=150,
        label='First name',
        widget=forms.TextInput(
            attrs={'class': 'input-group', 'placeholder': 'First name'}
        )
    )
    last_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={'class': 'input-group', 'placeholder': 'Last name'}
        )
    )
    email = forms.EmailField(
        max_length=150,
        widget=forms.TextInput(
            attrs={'class': 'input-group', 'placeholder': 'Email'}
        )
    )
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={'class': 'input-group', 'placeholder': 'Username'}
        )
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(
            attrs={'class': 'input-group', 'placeholder': 'Password'}),
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(
            attrs={'class': 'input-group', 'placeholder': 'Confirm Password'}),
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')



class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={
            'id': 'username',
            'placeholder': 'Username',
            'class': 'input-group',
            'required': True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'id': 'password',
            'placeholder': 'Password',
            'class': 'input-group',
            'required': True,
        })
    )



class CustomSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'custom-input-class'
            field.help_text = f'<span class="custom-helptext">{field.help_text}</span>'
            
        self.fields['new_password1'].widget.attrs.update({
            'class': 'custom-input-class',
            'placeholder': 'Enter your new password',
        })
        self.fields['new_password2'].widget.attrs.update({
            'class': 'custom-input-class',
            'placeholder': 'Confirm your new password',
        })