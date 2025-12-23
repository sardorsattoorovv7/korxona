from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
import os
from decimal import Decimal 

# Barcha modellar bitta joydan import qilindi
from .models import Order, MaterialTransaction, Material, Category, Worker 

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

import os
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

class OrderForm(forms.ModelForm):
    """Buyurtmani kiritish va tahrirlash uchun asosiy ModelForm."""
    
    panel_thickness = forms.ChoiceField(
        choices=PANEL_THICKNESS_CHOICES,
        required=True,
        label="Panel Qalinligi (mm)",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    # Ish turi - LIST, ESHIK va ARALASH turlari bilan
    worker_type = forms.ChoiceField(
        choices=[
            ('', '--- Ish Turini Tanlang ---'),
            ('LIST', 'List Ustasi uchun'),
            ('ESHIK', 'Eshik Ustasi uchun'),
            ('LIST_ESHIK', 'List va Eshik aralash'),
        ],
        required=True,
        label="Ish Turi",
        widget=forms.Select(attrs={'class': 'form-control', 'onchange': 'this.form.submit()'})
    )

    class Meta:
        model = Order
        # Modelda mavjud bo'lgan haqiqiy maydonlar
        fields = [
            'order_number', 'pdf_file', 'customer_name', 'product_name', 
            'comment', 'worker_comment', 'panel_kvadrat', 'total_price',
            'panel_thickness', 'worker_type',
            'assigned_workers', 'deadline', 'status',
            'worker_started_at', 'worker_finished_at',
            'start_image', 'finish_image',
        ]
        
        widgets = {
            'assigned_workers': forms.CheckboxSelectMultiple(),
            'deadline': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'worker_started_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'worker_finished_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Qoʻshimcha izohlar...', 'class': 'form-control'}),
            'worker_comment': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Usta izohlari...', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'order_number': forms.TextInput(attrs={'placeholder': 'Buyurtma raqami...', 'class': 'form-control'}),
            'customer_name': forms.TextInput(attrs={'placeholder': 'Xaridor nomi...', 'class': 'form-control'}),
            'product_name': forms.TextInput(attrs={'placeholder': 'Mahsulot nomi...', 'class': 'form-control'}),
            'panel_kvadrat': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control'}),
            'total_price': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control'}),
            'pdf_file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf'}),
            'start_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'finish_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Dinamik ravishda worker_type ni aniqlash
        worker_type = None
        if self.data and self.data.get('worker_type'):
            worker_type = self.data.get('worker_type')
        elif self.instance and self.instance.pk:
            worker_type = self.instance.worker_type

        # 1. Checkboxlar uchun Queryset filtrini sozlash
        if worker_type == 'LIST':
            self.fields['assigned_workers'].queryset = Worker.objects.filter(role='LIST')
            self.fields['assigned_workers'].label = "Faqat List Ustalarini Tanlang"
        elif worker_type == 'ESHIK':
            self.fields['assigned_workers'].queryset = Worker.objects.filter(role='ESHIK')
            self.fields['assigned_workers'].label = "Faqat Eshik Ustalarini Tanlang"
        elif worker_type == 'LIST_ESHIK':
            self.fields['assigned_workers'].queryset = Worker.objects.filter(role__in=['LIST', 'ESHIK'])
            self.fields['assigned_workers'].label = "List va Eshik Ustalarini Tanlang"
        else:
            # Tanlanmagan bo'lsa barcha ishchilarni ko'rsatish
            self.fields['assigned_workers'].queryset = Worker.objects.filter(role__in=['LIST', 'ESHIK'])
            self.fields['assigned_workers'].label = "Ustalarni Tanlang"

        self.fields['assigned_workers'].required = True

    def clean_order_number(self):
        order_number = self.cleaned_data.get('order_number')
        qs = Order.objects.filter(order_number=order_number)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Bu buyurtma raqami allaqachon mavjud")
        return order_number

    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get('pdf_file')
        if not pdf_file and self.instance and self.instance.pdf_file:
            return self.instance.pdf_file
        if not self.instance.pk and not pdf_file:
            raise ValidationError("PDF chizma yuklash majburiy")
        if pdf_file and pdf_file.size > 10 * 1024 * 1024:
            raise ValidationError("Fayl hajmi 10MB dan oshmasligi kerak")
        return pdf_file

    def clean(self):
        cleaned_data = super().clean()
        worker_type = cleaned_data.get('worker_type')
        assigned_workers = cleaned_data.get('assigned_workers')
        deadline = cleaned_data.get('deadline')

        # Deadline tekshiruvi
        if deadline and deadline < timezone.now() and not self.instance.pk:
            self.add_error('deadline', "Muddat o'tgan sana bo'lishi mumkin emas")

        # Ish turi va ustalar mutanosibligi
        if worker_type and assigned_workers:
            if worker_type == 'LIST':
                for w in assigned_workers:
                    if w.role != 'LIST':
                        self.add_error('assigned_workers', f"{w.get_full_name()} List ustasi emas!")
            
            elif worker_type == 'ESHIK':
                for w in assigned_workers:
                    if w.role != 'ESHIK':
                        self.add_error('assigned_workers', f"{w.get_full_name()} Eshik ustasi emas!")
            
            elif worker_type == 'LIST_ESHIK':
                has_list = any(w.role == 'LIST' for w in assigned_workers)
                has_eshik = any(w.role == 'ESHIK' for w in assigned_workers)
                if not has_list or not has_eshik:
                    self.add_error('assigned_workers', "Aralash ishda kamida bitta List va bitta Eshik ustasi bo'lishi shart.")

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
        label="Maxsulot nomi",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mahsulot nomi...',
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
                'step': '0.01',
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
    
    # 🔴 YANGI: Ish turi uchun filtr
    worker_type = forms.ChoiceField(
        choices=[
            ('', 'Barcha ish turlari'),
            ('LIST', 'List Ustasi uchun'),
            ('ESHIK', 'Eshik Ustasi uchun'),
        ],
        required=False,
        label="Ish Turi",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
