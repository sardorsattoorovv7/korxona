from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
import os
from decimal import Decimal 

# Barcha modellar bitta joydan import qilindi
from .models import Order, MaterialTransaction, Material, Category 


# -----------------------------------
# 1. BUYURTMA (ORDER) FORMALARI
# -----------------------------------

PANEL_THICKNESS_CHOICES = [
    ('', '--- Tanlang ---'),
    ('5', '5 mm'),
    ('10', '10 mm'),
    ('15', '15 mm'),
    ('20', '20 mm'), 
]

class OrderForm(forms.ModelForm):
    """Buyurtmani kiritish va tahrirlash uchun asosiy ModelForm."""
    
    panel_thickness = forms.ChoiceField(
        choices=PANEL_THICKNESS_CHOICES,
        required=True,
        label="Panel Qalinligi (mm)",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Order
        fields = [
            'order_number', 'pdf_file', 'customer_name', 'product_name', 
            'comment', 'worker_comment', 'panel_kvadrat', 'total_price',
            'panel_thickness',
            'assigned_workers', 'deadline', 'status',
            'worker_started_at', 'worker_finished_at',
            'start_image', 'finish_image',
        ]
        
        widgets = {
            'assigned_workers': forms.CheckboxSelectMultiple(),
            'deadline': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'worker_started_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'worker_finished_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Qoʻshimcha izohlar...', 'class': 'form-control'}),
            'worker_comment': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Usta izohlari...', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'order_number': forms.TextInput(attrs={'placeholder': 'Buyurtma raqami...', 'class': 'form-control'}),
            'customer_name': forms.TextInput(attrs={'placeholder': 'Xaridor nomi...', 'class': 'form-control'}),
            'product_name': forms.TextInput(attrs={'placeholder': 'Mahsulot nomi...', 'class': 'form-control'}),
            'panel_kvadrat': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control'}),
            'total_price': forms.NumberInput(attrs={'step': '1000', 'min': '0', 'class': 'form-control'}),
            'pdf_file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf'}),
            'start_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'finish_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
    
    def clean_order_number(self):
        order_number = self.cleaned_data.get('order_number')
        if not order_number:
            raise ValidationError("Buyurtma raqami majburiy")
        qs = Order.objects.filter(order_number=order_number)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Bu buyurtma raqami allaqachon mavjud")
        return order_number
    
    def clean_panel_kvadrat(self):
        panel_kvadrat = self.cleaned_data.get('panel_kvadrat')
        if panel_kvadrat is not None and panel_kvadrat < 0:
            raise ValidationError("Kvadrat manfiy bo'lishi mumkin emas")
        return panel_kvadrat
    
    def clean_total_price(self):
        total_price = self.cleaned_data.get('total_price')
        if total_price is not None and total_price < 0:
            raise ValidationError("Narx manfiy bo'lishi mumkin emas")
        return total_price
    
    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get('pdf_file')
        if not pdf_file and self.instance and self.instance.pdf_file:
            return self.instance.pdf_file
        if not self.instance.pk and not pdf_file:
            raise ValidationError("PDF fayl majburiy")
        if pdf_file:
            if pdf_file.size > 10 * 1024 * 1024:
                raise ValidationError("PDF fayl hajmi 10MB dan oshmasligi kerak (Maks. 10MB)")
            ext = os.path.splitext(pdf_file.name)[1].lower()
            if ext != '.pdf':
                raise ValidationError("Faqat PDF fayllarni yuklash mumkin")
        return pdf_file

    def clean(self):
        cleaned_data = super().clean()
        deadline = cleaned_data.get('deadline')
        if deadline and deadline < timezone.now():
            self.add_error('deadline', "Muddat o'tgan sana bo'lishi mumkin emas")
        worker_started_at = cleaned_data.get('worker_started_at')
        worker_finished_at = cleaned_data.get('worker_finished_at')
        if worker_started_at and worker_finished_at:
            if worker_finished_at < worker_started_at:
                self.add_error('worker_finished_at', "Tugatish vaqti boshlash vaqtidan oldin bo'lishi mumkin emas")
        return cleaned_data
    
class StartImageUploadForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['start_image']
        widgets = {
            'start_image': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control',
                'required': True
            })
        }
    
    def clean_start_image(self):
        start_image = self.cleaned_data.get('start_image')
        if not start_image:
            raise ValidationError("Boshlash rasmi majburiy") 
        if start_image.size > 5 * 1024 * 1024:
            raise ValidationError("Rasm hajmi 5MB dan oshmasligi kerak (Maks. 5MB)")
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        ext = os.path.splitext(start_image.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError("Faqat rasm fayllarini yuklash mumkin (JPG, PNG, GIF, BMP, WebP)")
        return start_image
    

class FinishImageUploadForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['finish_image']
        widgets = {
            'finish_image': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control',
                'required': True
            })
        }
    
    def clean_finish_image(self):
        finish_image = self.cleaned_data.get('finish_image')
        if not finish_image:
            raise ValidationError("Tugatish rasmi majburiy")
        if finish_image.size > 5 * 1024 * 1024:
            raise ValidationError("Rasm hajmi 5MB dan oshmasligi kerak (Maks. 5MB)")
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        ext = os.path.splitext(finish_image.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError("Faqat rasm fayllarini yuklash mumkin (JPG, PNG, GIF, BMP, WebP)")
        return finish_image

class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-control',
                'onchange': 'this.form.submit()'
            })
        }

# -----------------------------------
# 2. MATERIAL TRANSACTION FORMALARI
# -----------------------------------

# orders/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
import os
from decimal import Decimal 
from .models import Order, MaterialTransaction, Material, Category 

# ============================================
# Material Transaction Form uchun CUSTOM FIELD
# ============================================
from .models import Order, MaterialTransaction, Material, Category
class MaterialChoiceField(forms.ModelChoiceField):
    """Materiallarni to'liq ma'lumot bilan ko'rsatish"""
    
    def label_from_instance(self, obj):
        """Materialni: Nomi (BIRLIK) - Kategoriya - Qoldiq formatida ko'rsatish"""
        category_name = obj.category.name if obj.category else 'Kategoriyasiz'
        return f"{obj.name} ({obj.unit.upper()}) - Kategoriya: {category_name} - Qoldiq: {obj.quantity:.3f}"


class MaterialTransactionForm(forms.ModelForm):
    """Omborxona materiallari uchun Kirim yoki Chiqimni kiritish."""
    
    new_category_name = forms.CharField(
        max_length=100,
        required=False,
        label="Yangi Kategoriya Yaratish (Ixtiyoriy)",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Yangi kategoriya nomi...'
        }),
    )
    
    transaction_type = forms.ChoiceField(
        choices=MaterialTransaction.TRANSACTION_TYPES,
        widget=forms.RadioSelect(),
        label="Harakat Turi",
        initial='OUT' 
    )

    product_name = forms.CharField(
        label="Maxsulot nomi",  # Labelni "Maxsulot nomi" ga o'zgartirdik
        max_length=255,         # Matnning maksimal uzunligi
        required=False,         # Agar bu nom majburiy bo'lmasa
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mahsulot nomi...', # Placeholder matnni o'zgartirdik
            # Qoldiq kiritish uchun step, min_value kabi Decimal atributlar o'chirildi.
        })
    )
    quantity_change = forms.DecimalField(
        label="Miqdor",
        max_digits=10, 
        decimal_places=3,
        min_value=Decimal('0.001'),
        widget=forms.NumberInput(attrs={
            'step': '0.001', 
            'class': 'form-control',
            'placeholder': '0.000'
        })



    )
    create_batch_barcode = forms.BooleanField(required=False, label="Partiya Barcode yaratish")


    # ✅ TO'G'RI: Custom fieldni to'g'ri ishlatish
    material = MaterialChoiceField(
        queryset=Material.objects.all().select_related('category').order_by('name'),
        label="Material Tanlang",
        widget=forms.Select(attrs={
            'class': 'form-control', 
            'id': 'id_material_select'
        })
    )

    class Meta:
        model = MaterialTransaction
        fields = ['transaction_type', 'material', 'quantity_change', 'received_by', 'order', 'notes'] 
        
        widgets = {
            'received_by': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Kimdan olindi (Kirim) / Kimga berildi (Chiqim)'
            }),
            'order': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'form-control',
                'placeholder': 'Qo\'shimcha izohlar...'
            }),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Kategoriya field'i
        category_choices = [('', '--- Mavjud Kategoriya Tanlang ---')] + [
            (c.id, c.name) for c in Category.objects.all()
        ]
        self.fields['category'] = forms.ChoiceField(
            choices=category_choices,
            required=False,
            label="Mavjud Kategoriya",
            widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_category'})
        )
        
        # Order field'i
        self.fields['order'].required = False 
        self.fields['order'].queryset = Order.objects.all().order_by('-id')
        self.fields['order'].label = "Bog'liq buyurtma (Opsional)"
        
        # Radio buttonlar uchun class qo'shish
        self.fields['transaction_type'].widget.attrs.update({
            'class': 'form-check-input',
        })
    
    def clean(self):
        cleaned_data = super().clean()
        new_cat_name = cleaned_data.get('new_category_name')
        selected_cat_id = cleaned_data.get('category')
        
        # Kategoriya validatsiyasi
        if new_cat_name and selected_cat_id:
            raise forms.ValidationError(
                "Siz ham Yangi Kategoriya nomini, ham Mavjud Kategoriyani tanlay olmaysiz. Faqat bittasini kiriting/tanlang."
            )
        
        if new_cat_name and Category.objects.filter(name__iexact=new_cat_name).exists():
            self.add_error('new_category_name', "Bu kategoriya nomi allaqachon mavjud.")
        
        # Chiqim holatida qoldiq tekshiruvi
        transaction_type = cleaned_data.get('transaction_type')
        quantity = cleaned_data.get('quantity_change')
        material = cleaned_data.get('material')
        
        if material and transaction_type == 'OUT' and quantity:
            if quantity > material.quantity:
                self.add_error(
                    'quantity_change', 
                    f"Omborda yetarli miqdor mavjud emas. "
                    f"Mavjud: {material.quantity:.3f} {material.unit.upper()}, "
                    f"So'ralmoqda: {quantity:.3f} {material.unit.upper()}"
                )
        
        return cleaned_data



# forms.py - MaterialChoiceField va MaterialForm ni yangilash
from .models import Material

class MaterialChoiceField(forms.ModelChoiceField):
    """Materiallarni to'liq ma'lumot bilan ko'rsatish"""
    
    def label_from_instance(self, obj):
        """Materialni: Nomi → Maxsulot (BIRLIK) - Kategoriya - Qoldiq formatida ko'rsatish"""
        category_name = obj.category.name if obj.category else 'Kategoriyasiz'
        
        # 🔴 Maxsulot nomini ham qo'shamiz
        if obj.product_name:
            display_text = f"{obj.name} → {obj.product_name} ({obj.unit.upper()})"
        else:
            display_text = f"{obj.name} ({obj.unit.upper()})"
            
        return f"{display_text} - Kategoriya: {category_name} - Qoldiq: {obj.quantity:.3f}"


# 🔴 YANGI: Materialni yaratish/tahrirlash formasi
class MaterialForm(forms.ModelForm):
    """Material yaratish va tahrirlash uchun forma."""
    
    class Meta:
        model = Material
        fields = [
            'name', 'product_name', 'category', 'unit',
            'quantity', 'price_per_unit', 'min_stock_level'
        ]
        
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Material nomi...',
                'required': True
            }),
            'product_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Maxsulot nomi (ixtiyoriy)...'
            }),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'unit': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'price_per_unit': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '1000',
                'min': '0'
            }),
            'min_stock_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
        }
    
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name:
            raise ValidationError("Material nomi majburiy")
        
        qs = Material.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Bu material nomi allaqachon mavjud")
        return name
# -----------------------------------
# 3. FILTRLASH FORMALARI
# -----------------------------------

class OrderFilterForm(forms.Form):
    """Buyurtmalarni filtrlash uchun forma"""
    
    STATUS_CHOICES = [('', 'Barcha holatlar')] + list(Order.STATUS_CHOICES)
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    customer_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Xaridor nomi boʻyicha qidirish...'
        })
    )
    
    order_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Buyurtma raqami boʻyicha qidirish...'
        })
    )
    
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
