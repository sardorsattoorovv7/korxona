# orders/models.py
# Bu fayl korxonaning asosiy ma'lumotlar strukturasini (modellarini) belgilaydi.

from django.db import models
from django.contrib.auth import get_user_model 
from django.conf import settings
from decimal import Decimal
from django.utils import timezone # Order.save() funksiyasida kerak

User = get_user_model() 
# User modelini settings.AUTH_USER_MODEL orqali ham ishlatsa bo'ladi

# =======================================================================
# 1. KATEGORIYA MODELI (Material uchun baza)
# =======================================================================
class Category(models.Model):
    """Ombordagi materiallar uchun kategoriya."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Kategoriya Nomi")
    description = models.TextField(blank=True, verbose_name="Izoh")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"
        ordering = ['name']

    def __str__(self):
        return self.name

# =======================================================================
# 2. WORKER/USTA MODELI (Order uchun baza)
# =======================================================================
class Worker(models.Model):
    """Foydalanuvchini ustaxona rollari bilan bog'laydi."""
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
        username = getattr(self.user, 'username', 'Nomaʼlum foydalanuvchi')
        return f"{username} - {self.get_role_display()}"


# =======================================================================
# 3. MATERIAL (OMBORXONA KATALOGI) MODELI (Transaction uchun baza)
# Category ga bog'langan
# =======================================================================
# models.py - Material modelini yangilash
class Material(models.Model):
    """Omborxonadagi har bir material yoki xomashyo haqida ma'lumot."""
    
    UNIT_CHOICES = [
        ('kg', 'Kilogramm (kg)'),
        ('m2', 'Kvadrat Metr (m²)'),
        ('son', 'Dona / Son (ta)'),
        ('m', 'Metr (m)'),
        ('litr', 'Litr'),
    ]
    min_stock_level = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    max_stock_level = models.DecimalField(max_digits=10, decimal_places=3, default=0, null=True, blank=True)
    code = models.CharField(max_length=50, unique=True, null=True, blank=True, verbose_name="QR/Shtrix Kod")
    
    name = models.CharField(max_length=255, verbose_name="Material nomi", unique=True)
    
    # 🔴 YANGI: Maxsulot nomi uchun maydon
    product_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Maxsulot nomi",
        help_text="Ushbu materialdan tayyorlanadigan yoki bog'liq maxsulot nomi"
    )
    
    category = models.ForeignKey(
        Category, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="Material Kategoriyasi"
    )
    
    unit = models.CharField(
        max_length=10, 
        choices=UNIT_CHOICES, 
        default='son', 
        verbose_name="O'lchov birligi"
    )
    
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=3, 
        default=Decimal('0.000'), 
        verbose_name="Ombordagi joriy qoldiq"
    )
    price_per_unit = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        default=Decimal('0.00'), 
        verbose_name="Birlik narxi"
    )
    min_stock_level = models.DecimalField(
        max_digits=10, 
        decimal_places=3, 
        default=Decimal('0.000'), 
        verbose_name="Minimal qoldiq"
    )
    last_updated = models.DateTimeField(auto_now=True, verbose_name="Oxirgi yangilanish")

    class Meta:
        verbose_name = "Material"
        verbose_name_plural = "Materiallar (Omborxona)"
        ordering = ['name']

    def __str__(self):
        base_str = f"{self.name}"
        if self.product_name:
            base_str += f" → {self.product_name}"
        return f"{base_str} (Qoldiq: {self.quantity:,.3f} {self.unit.upper()})"
    



# =======================================================================
# 4. ORDER MODELI (MaterialTransaction va Notification uchun baza)
# Worker modeliga bog'langan
# =======================================================================
class Order(models.Model):
    """Buyurtma va ishlab chiqarish jarayonidagi uning holati."""
    
    STATUS_CHOICES = [
        ('KIRITILDI', "1. Kiritildi (Admin)"),
        ('TASDIQLANDI', "2. Tasdiqlandi (Menejer)"),
        ('RAD_ETILDI', "2. Rad Etildi (Menejer)"), 
        ('USTA_QABUL_QILDI', "3. Usta Qabul Qildi (Tovar Olingan)"),
        ('USTA_BOSHLA', "4. Usta Boshladi (Ishga Kirishdi)"),
        ('ISHDA', "5. Ishlab Chiqarishda (Menejer)"),
        ('USTA_TUGATDI', "6. Usta Yakunladi (Ish Tugatildi)"),
        ('TAYYOR', "7. Tayyor (Sifat Nazorati)"),
        ('BAJARILDI', "8. Bajarildi (Yakuniy)") 
    ]

    order_number = models.CharField(max_length=50, unique=True, verbose_name="Buyurtma Raqami")
    pdf_file = models.FileField(upload_to='order_pdfs/', verbose_name="PDF Fayl")
    customer_name = models.CharField(max_length=100, verbose_name="Xaridor Nomi")
    product_name = models.CharField(
        max_length=255, 
        verbose_name="Mahsulot Nomi",
        help_text="Buyurtma berilgan mahsulot yoki kategoriya nomi"
    ) 
    comment = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Izoh/Qo'shimcha Ma'lumot"
    )
    worker_comment = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Usta Izohlari"
    )
    
    panel_kvadrat = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Panel Kvadrat Metri (m²)")
    total_price = models.DecimalField(max_digits=15, decimal_places=2, default=0.00, verbose_name="Umumiy Narx (Summa)")
    
    assigned_workers = models.ManyToManyField(
        Worker, 
        related_name='assigned_orders', 
        verbose_name="Belgilangan Ustalar",
        blank=True
    )
    
    deadline = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Belgilangan Muddat (Deadline)",
        help_text="Usta bu muddatgacha ishni tugatishi kerak."
    )
    
    worker_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Usta Boshlagan Vaqti")
    worker_finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Usta Tugatgan Vaqti")

    # ... (Rasm maydonlari va tegishli status flaglari) ...
    start_image = models.ImageField(upload_to='order_photos/start/', null=True, blank=True, verbose_name="Ish Boshlash Rasmi")
    finish_image = models.ImageField(upload_to='order_photos/finish/', null=True, blank=True, verbose_name="Ish Yakunlash Rasmi")
    start_image_uploaded_at = models.DateTimeField(null=True, blank=True, verbose_name="Boshlash Rasmi Yuklangan Vaqt")
    finish_image_uploaded_at = models.DateTimeField(null=True, blank=True, verbose_name="Tugatish Rasmi Yuklangan Vaqt")
    deadline_breach_alert_sent = models.BooleanField(default=False, verbose_name="Muddat Buzilganligi Ogohlantirish Yuborildi")
    delayed_assignment_alert_sent = models.BooleanField(default=False, verbose_name="Ishga Berish Kechikkanligi Ogohlantirish Yuborildi")
    telegram_notified_overdue = models.BooleanField(default=False, verbose_name="Telegramga muddat haqida xabar berilgan")
    panel_thickness = models.CharField(max_length=50, blank=True, null=True, verbose_name="Panel Qalinligi (mm)")
    
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='KIRITILDI', verbose_name="Hozirgi Status")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_orders', verbose_name="Kirituvchi")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Kiritilgan vaqt")

    class Meta:
        verbose_name = "Buyurtma"
        verbose_name_plural = "Buyurtmalar"
        ordering = ['-created_at']

    def __str__(self):
        return f"Buyurtma #{self.order_number} - {self.get_status_display()}"

    def save(self, *args, **kwargs):
        # Rasm yuklangan vaqtlarni avtomatik yangilash
        if self.start_image and not self.start_image_uploaded_at:
            self.start_image_uploaded_at = timezone.now()
        if self.finish_image and not self.finish_image_uploaded_at:
            self.finish_image_uploaded_at = timezone.now()
        super().save(*args, **kwargs)


# =======================================================================
# 5. MATERIAL TRANSACTION MODELI (Material va Orderga bog'langan)
# =======================================================================
class MaterialTransaction(models.Model):
    """Omborxona materiallarining kirim-chiqim harakatlarini qayd etadi."""
    
    TRANSACTION_TYPES = [
        ('IN', 'Kirim (Omborga kirish)'),
        ('OUT', 'Chiqim (Ombordan chiqish/Sarflanish)'),
    ]

    material = models.ForeignKey(
        Material, # Material modeliga bog'landi
        on_delete=models.PROTECT, 
        verbose_name="Material nomi"
    )
    
    transaction_type = models.CharField(
        max_length=3, 
        choices=TRANSACTION_TYPES, 
        verbose_name="Harakat turi"
    )
    
    quantity_change = models.DecimalField(
        max_digits=10, 
        decimal_places=3, 
        verbose_name="Miqdordagi o'zgarish"
    )
    
    received_by = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Qabul qiluvchi shaxs/ustaxona"
    )
    order = models.ForeignKey(
        Order, # Order modeliga bog'landi
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Bog'liq buyurtma"
    )
    
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Amalga oshirdi"
    )
    
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Vaqti")
    
    notes = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Izoh/Sabab"
    )

    class Meta:
        verbose_name = "Material harakati"
        verbose_name_plural = "Material harakatlari (Tranzaksiyalar)"
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.get_transaction_type_display()}] {self.material.name}: {self.quantity_change} {self.material.unit}"


# =======================================================================
# 6. NOTIFICATION MODELI (User va Orderga bog'langan)
# =======================================================================
class Notification(models.Model):
    """Foydalanuvchilarga yuboriladigan tizim xabarlari."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="Qabul qiluvchi foydalanuvchi")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Tegishli buyurtma")
    message = models.CharField(max_length=255, verbose_name="Xabar matni")
    is_read = models.BooleanField(default=False, verbose_name="O'qilgan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Xabarnoma"
        verbose_name_plural = "Xabarnomalar"

    def __str__(self):
        return f"{self.user.username}: {self.message[:30]}..."

# Fayl oxiri
