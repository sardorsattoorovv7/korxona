# orders/signals.py (Tuzatilgan versiya)

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Order 
from .utils import send_telegram_notification
from django.conf import settings 
# Eslatma: django.contrib.sites modulini ishlatmaganingiz uchun Site import qilinmadi.

@receiver(post_save, sender=Order)
def order_notification_handler(sender, instance, created, **kwargs):
    
    # DEBUG UCHUN: Signal ishga tushganini tasdiqlash
    print(f"--- [DEBUG] SIGNAL ISHGA TUSHDI. Yangi buyurtma: {created}, ID: {instance.id} ---") 
    
    # Umumiy admin havola
    order_url = f"http://127.0.0.1:8000/admin/orders/order/{instance.id}/change/"
    
    # 1. YANGI ORDER QO'SHILSA
    if created:
        message = (f"🔔 <b>Yangi Buyurtma Qo'shildi!</b>\n\n"
                   f"Buyurtma raqami: <a href='{order_url}'>#{instance.id}</a>\n"
                   # ✅ customer_name ga tuzatildi
                   f"Mijoz: {instance.customer_name}\n" 
                   f"Kvadratura: {instance.panel_kvadrat} m²\n"
                   # ✅ deadline ga tuzatildi (deadline_date o'rniga)
                   f"Deadline: {instance.deadline.strftime('%Y-%m-%d')}") 
        send_telegram_notification(message)
        return

    # 2. STATUS 'BAJARILDI' GA O'TISHINI TEKSHIRISH
    if instance.status == 'BAJARILDI' and instance.worker_finished_at:
        
        # Tayinlangan xodim nomini aniqlash
        assigned_worker = instance.assigned_workers.first()
        worker_name = assigned_worker.user.get_full_name() if assigned_worker and assigned_worker.user else 'Noma’lum'
        
        message = (f"✅ <b>Buyurtma Yakunlandi!</b>\n\n"
                   f"Buyurtma raqami: <a href='{order_url}'>#{instance.id}</a>\n"
                   f"Usta: {worker_name}\n"
                   f"Yakunlandi: {instance.worker_finished_at.strftime('%Y-%m-%d %H:%M')}")
        send_telegram_notification(message)

# orders/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from .models import Material, MaterialTransaction

@receiver(post_save, sender=MaterialTransaction)
def update_material_stock(sender, instance, created, **kwargs):
    """Yangi tranzaksiya yaratilganda Materialning qoldig'ini yangilaydi."""
    if created:
        material = instance.material
        quantity_change = instance.quantity_change
        transaction_type = instance.transaction_type

        with transaction.atomic():
            # Material ob'ektini DB dan qayta yuklaymiz (raqobatlarni oldini olish uchun)
            material = Material.objects.select_for_update().get(pk=material.pk)
            
            if transaction_type == 'IN':
                material.quantity += quantity_change
            elif transaction_type == 'OUT':
                material.quantity -= quantity_change
                
            material.save()
