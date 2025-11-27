# eco_prom/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings 
from django.conf.urls.static import static 

# YANGI IMPORT
from django.views.generic.base import RedirectView # <-- QO'SHILADI

urlpatterns = [
    # 1. Admin panel
    path('admin/', admin.site.urls),
    
    # 2. ASOSIY SAHIFADAN YO'NALTIRISH (Redirect)
    # '/' ga kirilsa, to'g'ridan-to'g'ri '/orders/' ga yo'naltiramiz
    path('', RedirectView.as_view(url='orders/', permanent=False), name='root_redirect'), # <-- QO'SHILADI
    
    # 3. Autentifikatsiya URL'lari (login, logout, parolni tiklash)
    # Bu /login/, /logout/, /password_reset/ manzilini o'rnatadi.
    path('', include('django.contrib.auth.urls')), 
    
    # 4. 'orders' ilovasining URL'lari
    path('orders/', include('orders.urls')), 
]

# Media fayllarini yetkazish (agar DEBUG = True bo'lsa)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)