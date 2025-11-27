from django.db import models
from django.contrib.auth import get_user_model 

User = get_user_model() 

# -----------------------------------
# 1. WORKER/USTA MODELI
# -----------------------------------
class Worker(models.Model):
    ROLE_CHOICES = [
        ('PANEL', "Panel Ustasi"),
        ('LIST', "List Ustasi"),
        ('ESHIK', "Eshik Ustasi"),
        ('UGOL', "Ugol Ustasi"),
    ]

    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='worker_profile', 
        verbose_name="Foydalanuvchi"
    )
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, verbose_name="Usta Roli")

    class Meta:
        verbose_name = "Usta"
        verbose_name_plural = "Ustalar"

    def __str__(self):
        # Agar user obyekti None bo'lsa xato bermasligi uchun tekshiramiz
        username = getattr(self.user, 'username', 'Nomaʼlum foydalanuvchi')
        return f"{username} - {self.get_role_display()}" 


# -----------------------------------
# 2. ORDER MODELI 
# -----------------------------------
class Order(models.Model):
    # Kengaytirilgan STATUS_CHOICES
    STATUS_CHOICES = [
        ('KIRITILDI', "1. Kiritildi (Admin)"),
        ('TASDIQLANDI', "2. Tasdiqlandi (Menejer)"),
        ('RAD_ETILDI', "2. Rad Etildi (Menejer)"), 
        
        # Usta Qadamlari
        ('USTA_QABUL_QILDI', "3. Usta Qabul Qildi (Tovar Olingan)"),
        ('USTA_BOSHLA', "4. Usta Boshladi (Ishga Kirishdi)"),
        
        ('ISHDA', "5. Ishlab Chiqarishda (Boshliq)"),
        
        ('USTA_TUGATDI', "6. Usta Yakunladi (Ish Tugatildi)"),
        
        ('TAYYOR', "7. Tayyor (Sifat Nazorati)"),
        ('BAJARILDI', "8. Bajarildi (Yakuniy)") 
    ]
    
    order_number = models.CharField(max_length=50, unique=True, verbose_name="Buyurtma Raqami")
    pdf_file = models.FileField(upload_to='order_pdfs/', verbose_name="PDF Fayl")
    customer_name = models.CharField(max_length=100, verbose_name="Xaridor Nomi")
    
    panel_kvadrat = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Panel Kvadrat Metri (m²)")
    total_price = models.DecimalField(max_digits=15, decimal_places=2, default=0.00, verbose_name="Umumiy Narx (Summa)")
    
    assigned_workers = models.ManyToManyField(
        Worker, 
        related_name='assigned_orders', 
        verbose_name="Belgilangan Ustalar",
        blank=True
    )
    
    # Muddat
    deadline = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Belgilangan Muddat (Deadline)",
        help_text="Usta bu muddatgacha ishni tugatishi kerak. Ushbu sana o'tgach, Admin/Menejerlarga ogohlantirish yuboriladi."
    )
    
    # Ish Boshlash va Tugatish vaqti
    worker_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Usta Boshlagan Vaqti")
    worker_finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Usta Tugatgan Vaqti")

    # ✅ Yangi: Rasm maydonlari (Usta Boshlash/Tugatish uchun)
    start_image = models.ImageField(
        upload_to='order_photos/start/', 
        null=True, 
        blank=True, 
        verbose_name="Ish Boshlash Rasmi"
    )
    finish_image = models.ImageField(
        upload_to='order_photos/finish/', 
        null=True, 
        blank=True, 
        verbose_name="Ish Yakunlash Rasmi"
    )
    
    # Ogohlantirish yuborilganligi holati
    deadline_breach_alert_sent = models.BooleanField(default=False, verbose_name="Muddat Buzilganligi Ogohlantirish Yuborildi")

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='KIRITILDI', verbose_name="Hozirgi Status")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_orders', verbose_name="Kirituvchi")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Kiritilgan vaqt")

    class Meta:
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"
        ordering = ['-created_at']

    def __str__(self):
        return f"Buyurtma #{self.order_number} - {self.get_status_display()}"


# -----------------------------------
# 3. NOTIFICATION MODELI 
# -----------------------------------
class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="Qabul qiluvchi foydalanuvchi")
    order = models.ForeignKey('Order', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Tegishli buyurtma")
    message = models.CharField(max_length=255, verbose_name="Xabar matni")
    is_read = models.BooleanField(default=False, verbose_name="O'qilgan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Xabarnoma"
        verbose_name_plural = "Xabarnomalar"

    def __str__(self):
        return f"{self.user.username}: {self.message[:30]}..."