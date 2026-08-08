from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    usda_api_key:str
    usda_base_url: str = "https://api.nal.usda.gov/fdc/v1"
    gemini_api_key:str
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url:str = "https://generativelanguage.googleapis.com/v1beta"
    supabase_url:str
    database_url:str
    jwt_audience:str = "authenticated"


    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"


    class Config:
        env_file =".env"


settings = Settings()

