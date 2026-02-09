from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


# This serializer is only for functional addition to already working Token serializer
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        # Custom response field
        data["user"] = {
            "id": self.user.id,
            "username": self.user.username,
        }
        return data
