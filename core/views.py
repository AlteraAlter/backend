from django.shortcuts import render,redirect
from django.contrib.sites.shortcuts import get_current_site
from django.http import HttpResponse
from .forms import RegisterForm, LoginForm
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages

from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.forms import SetPasswordForm
# Create your views here.
def signin(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('home')
            else:
                form.add_error(None, "Invalid email or password")
    else:
        form = LoginForm()


    return render(request, 'core/signin.html', {'form': form})


def signup(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data['username']
            password = form.cleaned_data['password1']

            user = authenticate(username=username, password=password)
            if user:
                login(request, user)
                return redirect('home')
        else:
            print('Form errors:', form.errors)
            
    else:
        form = RegisterForm()
    return render(request, 'core/signup.html', {'form': form}) 


def logout_(request):
    logout(request)
    return redirect('home')

def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')

        associated_user = User.objects.filter(email=email).first()
        if associated_user:
            subject = 'Password Reset Requested'
            email_template_name = 'core/password_reset_email.html'
            context = {
                'email': associated_user.email,
                'domain': get_current_site(request).domain,
                'site_name': "Happy Holiday",
                'uid': urlsafe_base64_encode(force_bytes(associated_user.pk)),
                'token': default_token_generator.make_token(associated_user),
                'protocol': 'https' if request.is_secure() else 'http',
            }

            email_content = render_to_string(email_template_name, context)
            send_mail(subject, email_content, '200107017@stu.sdu.edu.kz', [associated_user.email], fail_silently=False)
        messages.success(request, 'A reset code has been sent to your email address.')
            
    return render(request, 'core/forgot-password.html', {})





def password_reset_success(request):
    return render(request, 'core/password_reset_success.html', {})

def change_password(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk = uid)
        print(uid, user)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        print(urlsafe_base64_encode(uidb64).decode())
        user = None

    if user and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            form = SetPasswordForm(user, request.POST)
            print(form)
            if form.is_valid():
                form.save()
                return redirect('home')
        else:
            form = SetPasswordForm(user)
        return render(request, 'core/password_reset.html', {'form': form, 'correct': True})
    else:
        return render(request, 'core/password_reset.html', {'correct': False})



def home(request):
    user_id = request.user.id

    return render(request, 'core/home.html', {'id': user_id})

def profile(request, id):
    user = User.objects.get(pk=id)

    return render(request, 'core/profile.html', {'user': user, 'id': id})