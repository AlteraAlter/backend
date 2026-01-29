from rest_framework_simplejwt.serializers import TokenObtainSlidingSerializer

# This serializer is only for functional addition to already working Token serializer
class CustomTokenObtainSlidingSerializer(TokenObtainSlidingSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        #Custom response field
        data["user"] = {
            "id": self.user.id,
            "username": self.user.username,
            "email": self.user.email,
        }
        print(f"USER: {self.user}")
        return data