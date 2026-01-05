# orders/models.py
import uuid
from django.db import models
from django.contrib.auth import get_user_model 
from django.conf import settings
from decimal import Decimal
from django.utils import timezone

User = get_user_model() 

# =======================================================================
# 1. KATEGORIYA MODELI
# =======================================================================
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Kategoriya Nomi")
    description = models.TextField(blank=True, verbose_name="Izoh")
    # created_at = models.DateTimeField(auto_now_add=True)
    # models.py ichida
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"
        ordering = ['name']

    def __str__(self):
        return self.name

# =======================================================================
# 2. WORKER/USTA MODELI
# =======================================================================
class Worker(models.Model):
    ROLE_CHOICES = [
        ('PANEL', "Panel Ustasi"),
        ('LIST', "List Ustasi"),
        ('ESHIK', "Eshik Ustasi"),
        ('UGOL', "Ugol Ustasi"),
        ('LIST_ESHIK', "List va Eshik ustalari"),
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
# 3. MATERIAL MODELI
# =======================================================================
class Material(models.Model):
    UNIT_CHOICES = [
        ('kg', 'Kilogramm (kg)'),
        ('m2', 'Kvadrat Metr (m²)'),
        ('son', 'Dona / Son (ta)'),
        ('m', 'Metr (m)'),
        ('litr', 'Litr'),
    ]
    
    name = models.CharField(max_length=255, verbose_name="Material nomi", unique=True)
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
    max_stock_level = models.DecimalField(
        max_digits=10, 
        decimal_places=3, 
        default=0, 
        null=True, 
        blank=True,
        verbose_name="Maksimal qoldiq"
    )
    code = models.CharField(max_length=50, unique=True, null=True, blank=True, verbose_name="QR/Shtrix Kod")
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
# 4. ORDER MODELI
# =======================================================================
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError

class Order(models.Model):
    STATUS_CHOICES = [
        ('KIRITILDI', "1. Kiritildi (Admin)"),
        ('TASDIQLANDI', "2. Tasdiqlandi (Menejer)"),
        ('RAD_ETILDI', "2. Rad Etildi (Menejer)"), 
        ('USTA_QABUL_QILDI', "3. Usta Qabul Qildi"),
        ('USTA_BOSHLA', "4. Usta Boshladi"),
        ('ISHDA', "5. Ishlab Chiqarishda"),
        ('USTA_TUGATDI', "6. Usta Yakunladi"),
        ('TAYYOR', "7. Tayyor"),
        ('BAJARILDI', "8. Bajarildi") 
    ]

    WORKER_TYPE_CHOICES = [
        ('LIST', 'List Ustasi'),
        ('ESHIK', 'Eshik Ustasi'),
        ('LIST_ESHIK', 'List va Eshik Ustasi'), # Universal rol buyurtma turi sifatida
        ('PANEL', 'Panel Ustasi'),
        ('UGOL', 'Ugol Ustasi'),
    ]

    PANEL_TYPE_CHOICES = [
        ('PIR', 'PIR Panel'),
        ('PUR', 'PUR Panel'),
    ]

    PANEL_SUBTYPE_CHOICES = [
        ('TOM', 'Tom'),
        ('SECRETPIR', 'SecretPir'),
        ('SOVUTGICH', 'PIR Sovutgich')
    ]

    PANEL_THICKNESS_CHOICES = [
        ('5', '5 sm'),
        ('8', '8 sm'),
        ('10', '10 sm'),
        ('15', '15 sm')
    ]

    ESHIK_TURI_CHOICES  = [
        ('F1','F1'),('F2','F2'),('F3','F3'),('F4','F4'),
        ('F5','F5'),('F6','F6'),('F7','F7'),('F8','F8')
    ]

    # models.py ichidagi Order klasiga qo'shing:

    product_name = models.CharField(max_length=255, verbose_name="Mahsulot nomi", blank=True, null=True)
    worker_comment = models.TextField(blank=True, null=True, verbose_name="Usta izohi")
    worker_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Ish boshlangan vaqt")
    worker_finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Ish yakunlangan vaqt")
    needs_manager_approval = models.BooleanField(default=False, verbose_name="Menejer tasdig'i kerak")
    # models.py ichida
    parent_order = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='sub_orders')
    # 1. Asosiy identifikatsiya
    order_number = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Buyurtma Raqami",
        editable=False
    )
    customer_unique_id = models.CharField(
        max_length=50, 
        verbose_name="Mijoz ID", 
        help_text="Ko'p martalik mijoz identifikatori"
    )
    customer_name = models.CharField(max_length=150, verbose_name="Xaridor Nomi")
    

    @property
    def remaining_amount(self):
        """Qoldiq summani hisoblaydi"""
        total = self.total_price or 0
        prepaid = self.prepayment or 0
        return total - prepaid
    
    def add_payment(self, amount):
        """Mavjud zalog ustiga yangi to'lovni qo'shadi"""
        if amount > 0:
            self.prepayment = (self.prepayment or 0) + amount
            self.save()
            return True
        return False
    # 2. Ish turi va texnik parametrlar
    worker_type = models.CharField(max_length=15, choices=WORKER_TYPE_CHOICES, default='LIST')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='KIRITILDI')
    
    # Eshik uchun
    eshik_turi = models.CharField(max_length=5, choices=ESHIK_TURI_CHOICES , blank=True, null=True)
    zamokli_eshik = models.BooleanField(default=False, verbose_name="Zamokli")

    # Panel uchun
    panel_type = models.CharField(max_length=10, choices=PANEL_TYPE_CHOICES, blank=True, null=True)
    panel_subtype = models.CharField(max_length=20, choices=PANEL_SUBTYPE_CHOICES, blank=True, null=True)
    panel_thickness = models.CharField(max_length=3, choices=PANEL_THICKNESS_CHOICES, blank=True, null=True)
    panel_kvadrat = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # 3. Moliyaviy qism
    total_price = models.DecimalField(max_digits=15, decimal_places=2, default=0.00, verbose_name="Umumiy Narx")
    prepayment = models.DecimalField(max_digits=15, decimal_places=2, default=0.00, verbose_name="Zalog (Oldindan to'lov)")

    # 4. Fayl va muddat
    pdf_file = models.FileField(upload_to='order_pdfs/', verbose_name="PDF Chizma", blank=True, null=True)
    deadline = models.DateTimeField(null=True, blank=True, verbose_name="Tugallanish muddati")
    
    # 5. Jarayon nazorati
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='KIRITILDI')
    assigned_workers = models.ManyToManyField('Worker', related_name='assigned_orders', blank=True)
    comment = models.TextField(blank=True, null=True, verbose_name="Admin izohi")
    
    # Rasmlar va vaqtlar
    start_image = models.ImageField(upload_to='order_photos/start/', null=True, blank=True)
    finish_image = models.ImageField(upload_to='order_photos/finish/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def clean(self):
        # 1. Panel uchun tekshiruv
        if self.worker_type == 'PANEL' and not self.panel_type:
            raise ValidationError("Panel turi kiritilishi shart.")

        # 2. ESHIK yoki LIST_ESHIK (Universal) uchun tekshiruv (SHU YERNI O'ZGARTIRDIK)
        if self.worker_type in ['ESHIK', 'LIST_ESHIK'] and not self.eshik_turi:
            raise ValidationError("Eshik yoki Universal usta tanlanganda eshik turi kiritilishi shart.")

        # 3. Panel qalinligi (thickness) bo'yicha maxsus tekshiruvlar
        if self.panel_type == 'PIR':
            if self.panel_subtype == 'SOVUTGICH' and self.panel_thickness not in ['5','10','15']:
                raise ValidationError("PIR Sovutgich uchun thickness 5, 10 yoki 15 sm bo‘lishi kerak.")
            
            if self.panel_subtype == 'SECRETPIR' and self.panel_thickness not in ['5','8']:
                raise ValidationError("SecretPir uchun thickness 5 yoki 8 sm bo‘lishi kerak.")
            
            if self.panel_subtype == 'TOM' and self.panel_thickness != '5':
                raise ValidationError("Tom panel uchun thickness 5 sm bo‘lishi kerak.")
        
        if self.panel_type == 'PUR' and self.panel_thickness != '5':
            raise ValidationError("PUR panel uchun thickness 5 sm bo‘lishi kerak.")



    def save(self, *args, **kwargs):
        # 1. Avtomatik buyurtma raqami (Siz yozgan qism)
        if not self.order_number:
            today = timezone.now()
            year_prefix = today.strftime("%Y")
            last_order = Order.objects.filter(order_number__startswith=f"ORD-{year_prefix}").order_by('-id').first()
            if last_order:
                try:
                    last_num = int(last_order.order_number.split('-')[-1])
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            self.order_number = f"ORD-{year_prefix}-{new_num:04d}"

        # 2. Status o'zgarganini aniqlash (Zanjir uchun eng muhim joy)
        old_status = None
        if self.pk:
            # Bazadagi eski holatini olamiz
            old_instance = Order.objects.filter(pk=self.pk).first()
            if old_instance:
                old_status = old_instance.status

        # Shart: Status endi 'USTA_TUGATDI' bo'ldi va avval bunaqa emas edi
        should_create_next = (self.status == 'USTA_TUGATDI' and old_status != 'USTA_TUGATDI')
        
        # Asosiy saqlash amali
        super().save(*args, **kwargs)

        # 3. KEYINGI BOSQICH (Zanjir)
        if should_create_next:
            # Takrorlanishni oldini olish: bitta buyurtmadan faqat bitta sub_order ochish
            has_sub_orders = Order.objects.filter(parent_order=self).exists()
            if not has_sub_orders:
                next_worker_type = None
                
                if self.worker_type in ['LIST', 'ESHIK', 'LIST_ESHIK']:
                    next_worker_type = 'PANEL'
                elif self.worker_type == 'PANEL':
                    next_worker_type = 'UGOL'

                if next_worker_type:
                    Order.objects.create(
                        customer_unique_id=self.customer_unique_id,
                        customer_name=self.customer_name,
                        # Mahsulot nomini chiroyli qilish
                        product_name=f"{self.product_name} (Navbat: {next_worker_type})",
                        worker_type=next_worker_type,
                        parent_order=self,
                        panel_type=self.panel_type,
                        panel_subtype=self.panel_subtype,
                        panel_thickness=self.panel_thickness,
                        panel_kvadrat=self.panel_kvadrat,
                        eshik_turi=self.eshik_turi, # Eshik turi ham o'tsin (kerak bo'lishi mumkin)
                        pdf_file=self.pdf_file,
                        status='KIRITILDI',
                        created_by=self.created_by
                    )
# =======================================================================
# 5. MATERIAL TRANSACTION MODELI
# =======================================================================
class MaterialTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('IN', 'Kirim (Omborga kirish)'),
        ('OUT', 'Chiqim (Ombordan chiqish/Sarflanish)'),
    ]

    material = models.ForeignKey(
        Material, 
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
    transaction_barcode = models.CharField(
        max_length=100, 
        unique=True, 
        null=True, 
        blank=True, 
        verbose_name="Partiya Barcode"
    )
    received_by = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Qabul qiluvchi shaxs/ustaxona"
    )
    order = models.ForeignKey(
        Order, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Bog'liq buyurtma"
    )
    performed_by = models.ForeignKey(
        User,
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

    def save(self, *args, **kwargs):
        # 1. Barcode faqat bo'sh bo'lsa va faqat KIRIM bo'lsa yaratilishi kerak
        if not self.transaction_barcode and self.transaction_type == 'IN':
            # Material nomidan xavfsiz foydalanish (probel va belgilarni tozalash)
            import re
            prefix = re.sub(r'[^a-zA-Z0-9]', '', self.material.name)[:3].upper() if self.material else "MTR"
            
            # Unikal id qo'shish
            unique_id = uuid.uuid4().hex[:6].upper()
            self.transaction_barcode = f"{prefix}-{unique_id}"
        
        # 2. Agar Chiqim (OUT) bo'lsa, barcodeni null saqlash yoki 
        # chiqim qilingan partiya kodini qo'lda kiritishni talab qilish mumkin.
        
        super().save(*args, **kwargs)

    def __str__(self):
        # Miqdor yoniga birligini ham qo'shib qo'ysak, adminga oson bo'ladi
        unit = self.material.unit if self.material else ""
        return f"[{self.get_transaction_type_display()}] {self.material.name}: {self.quantity_change} {unit}"

# =======================================================================
# 6. NOTIFICATION MODELI
# =======================================================================
class Notification(models.Model):
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
    


from django.db import models
import string, random

class Customer(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True, null=True)
    unique_id = models.CharField(max_length=10, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.unique_id:
            # 6 raqamli unik ID yaratish
            self.unique_id = ''.join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.unique_id})"
