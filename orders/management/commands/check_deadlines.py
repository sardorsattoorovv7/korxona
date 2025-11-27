# orders/management/commands/check_deadlines.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from orders.models import Order
from orders.utils import send_telegram_notification # Telegram funksiyasini import qilamiz

class Command(BaseCommand):
    help = 'Muddatlari tugagan ammo Bajarilmagan buyurtmalar haqida Telegramda xabar beradi.'

    def handle(self, *args, **options):
        # 1. Bugungi sanani (vaqtni) olamiz
        now = timezone.now()
        
        # 2. Muddatlari o'tib ketgan va 'BAJARILDI' statusida bo'lmagan buyurtmalarni topamiz
        overdue_orders = Order.objects.filter(
            deadline__lt=now,              # Muddat o'tib ketgan (deadline < hozirgi vaqt)
            status__in=['KIRITILDI', 'QABUL QILINDI', 'BAJARILMOQDA'] # Bajarilmagan statuslar
        ).exclude(
            telegram_notified_overdue=True # Avval xabar berilmagan bo'lsin
        )

        if overdue_orders.exists():
            self.stdout.write(self.style.WARNING(f"⚠️ {overdue_orders.count()} ta muddat o'tgan buyurtma topildi."))
            
            for order in overdue_orders:
                # Telegram xabari matnini tayyorlash
                order_url = f"http://127.0.0.1:8000/admin/orders/order/{order.id}/change/"
                
                message = (f"❗️ <b>MUDDATI O'TDI!</b> ⏳\n\n"
                           f"Buyurtma raqami: <a href='{order_url}'>#{order.id}</a>\n"
                           f"Mijoz: {order.customer_name}\n"
                           f"Muddat: {order.deadline.strftime('%Y-%m-%d %H:%M')}\n"
                           f"Status: {order.get_status_display()}\n\n"
                           f"Iltimos, zudlik bilan tekshiring!")

                # Xabarni yuborish
                send_telegram_notification(message)
                
                # Xabar yuborilganini belgilash
                order.telegram_notified_overdue = True
                order.save(update_fields=['telegram_notified_overdue'])

            self.stdout.write(self.style.SUCCESS('✅ Muddat o\'tgan buyurtmalar haqida xabarlar yuborildi.'))
        else:
            self.stdout.write(self.style.SUCCESS('Buyurtmalarning muddati o\'tmagan.'))