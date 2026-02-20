from django.db import models
from django.contrib.auth.models import User
# Create your models here.

class AdminRequestLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.endpoint} [{self.method}]"
    
    
    
class ImageStorage(models.Model):
    ean = models.IntegerField()
    path = models.ImageField(upload_to="images/")