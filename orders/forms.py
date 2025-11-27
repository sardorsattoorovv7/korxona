from django import forms
from django.core.exceptions import ValidationError
from .models import Order
import os
from django.utils import timezone

class OrderForm(forms.ModelForm):
    """
    Buyurtmani kiritish va tahrirlash uchun asosiy ModelForm.
    """
    class Meta:
        model = Order
        fields = [
            'order_number',
            'pdf_file',
            'customer_name',
            'product_name', 
            'comment',      
            'worker_comment',  # YANGI QO'SHILDI
            'panel_kvadrat',
            'total_price',
            'assigned_workers',
            'deadline',
            'status',
            'worker_started_at', 
            'worker_finished_at',
            'start_image',
            'finish_image',
        ]
        
        widgets = {
            'assigned_workers': forms.CheckboxSelectMultiple(),
            'deadline': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
            'worker_started_at': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
            'worker_finished_at': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
            'comment': forms.Textarea(attrs={
                'rows': 3, 
                'placeholder': 'Qoʻshimcha izohlar...',
                'class': 'form-control'
            }),
            'worker_comment': forms.Textarea(attrs={  # YANGI QO'SHILDI
                'rows': 3, 
                'placeholder': 'Usta izohlari...',
                'class': 'form-control'
            }),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'order_number': forms.TextInput(attrs={
                'placeholder': 'Buyurtma raqami...',
                'class': 'form-control'
            }),
            'customer_name': forms.TextInput(attrs={
                'placeholder': 'Xaridor nomi...',
                'class': 'form-control'
            }),
            'product_name': forms.TextInput(attrs={
                'placeholder': 'Mahsulot nomi...',
                'class': 'form-control'
            }),
            'panel_kvadrat': forms.NumberInput(attrs={
                'step': '0.01', 
                'min': '0',
                'class': 'form-control'
            }),
            'total_price': forms.NumberInput(attrs={
                'step': '1000', 
                'min': '0',
                'class': 'form-control'
            }),
            'pdf_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf'
            }),
            'start_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'finish_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
    
    def clean_order_number(self):
        """Buyurtma raqami takrorlanmasligini tekshirish"""
        order_number = self.cleaned_data.get('order_number')
        if not order_number:
            raise ValidationError("Buyurtma raqami majburiy")
            
        if Order.objects.filter(order_number=order_number).exists():
            if self.instance and self.instance.pk:
                if Order.objects.filter(order_number=order_number).exclude(pk=self.instance.pk).exists():
                    raise ValidationError("Bu buyurtma raqami allaqachon mavjud")
            else:
                raise ValidationError("Bu buyurtma raqami allaqachon mavjud")
        return order_number
    
    def clean_panel_kvadrat(self):
        """Kvadrat manfiy bo'lmasligini tekshirish"""
        panel_kvadrat = self.cleaned_data.get('panel_kvadrat')
        if panel_kvadrat is not None and panel_kvadrat < 0:
            raise ValidationError("Kvadrat manfiy bo'lishi mumkin emas")
        return panel_kvadrat
    
    def clean_total_price(self):
        """Narx manfiy bo'lmasligini tekshirish"""
        total_price = self.cleaned_data.get('total_price')
        if total_price is not None and total_price < 0:
            raise ValidationError("Narx manfiy bo'lishi mumkin emas")
        return total_price
    
    def clean_pdf_file(self):
        """PDF fayl hajmini va formatini tekshirish"""
        pdf_file = self.cleaned_data.get('pdf_file')
        
        if not self.instance.pk and not pdf_file:
            raise ValidationError("PDF fayl majburiy")
            
        if pdf_file:
            if pdf_file.size > 10 * 1024 * 1024:
                raise ValidationError("PDF fayl hajmi 10MB dan oshmasligi kerak")
            
            ext = os.path.splitext(pdf_file.name)[1].lower()
            if ext != '.pdf':
                raise ValidationError("Faqat PDF fayllarni yuklash mumkin")
        
        return pdf_file

    def clean(self):
        """Umumiy validatsiya"""
        cleaned_data = super().clean()
        
        deadline = cleaned_data.get('deadline')
        if deadline and deadline < timezone.now():
            raise ValidationError({
                'deadline': "Muddat o'tgan sana bo'lishi mumkin emas"
            })
        
        worker_started_at = cleaned_data.get('worker_started_at')
        worker_finished_at = cleaned_data.get('worker_finished_at')
        
        if worker_started_at and worker_finished_at:
            if worker_finished_at < worker_started_at:
                raise ValidationError({
                    'worker_finished_at': "Tugatish vaqti boshlash vaqtidan oldin bo'lishi mumkin emas"
                })
        
        return cleaned_data


class StartImageUploadForm(forms.ModelForm):
    """
    Usta ishni boshlaganda rasm yuklash uchun forma.
    """
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
        """Boshlash rasmini validatsiya qilish"""
        start_image = self.cleaned_data.get('start_image')
        
        if not start_image:
            raise ValidationError("Boshlash rasmi majburiy")
        
        if start_image.size > 5 * 1024 * 1024:
            raise ValidationError("Rasm hajmi 5MB dan oshmasligi kerak")
        
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        ext = os.path.splitext(start_image.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError("Faqat rasm fayllarini yuklash mumkin (JPG, PNG, GIF, BMP, WebP)")
        
        return start_image


class FinishImageUploadForm(forms.ModelForm):
    """
    Usta ishni tugatganda rasm yuklash uchun forma.
    """
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
        """Tugatish rasmini validatsiya qilish"""
        finish_image = self.cleaned_data.get('finish_image')
        
        if not finish_image:
            raise ValidationError("Tugatish rasmi majburiy")
        
        if finish_image.size > 5 * 1024 * 1024:
            raise ValidationError("Rasm hajmi 5MB dan oshmasligi kerak")
        
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        ext = os.path.splitext(finish_image.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError("Faqat rasm fayllarini yuklash mumkin (JPG, PNG, GIF, BMP, WebP)")
        
        return finish_image


# Qo'shimcha: Status o'zgartirish formasi
class OrderStatusForm(forms.ModelForm):
    """
    Faqat statusni o'zgartirish uchun forma
    """
    class Meta:
        model = Order
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-control',
                'onchange': 'this.form.submit()'
            })
        }


# Qo'shimcha: Filtrlash formasi
class OrderFilterForm(forms.Form):
    """
    Buyurtmalarni filtrlash uchun forma
    """
    STATUS_CHOICES = [
        ('', 'Barcha holatlar'),
        ('KIRITILDI', 'Kiritildi'),
        ('TASDIQLANDI', 'Tasdiqlandi'),
        ('USTA_QABUL_QILDI', 'Usta Qabul Qildi'),
        ('USTA_BOSHLA', 'Usta Boshladi'),
        ('ISHDA', 'Ishda'),
        ('USTA_TUGATDI', 'Usta Tugatdi'),
        ('TAYYOR', 'Tayyor'),
        ('BAJARILDI', 'Bajarildi'),
        ('RAD_ETILDI', 'Rad Etildi'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'onchange': 'this.form.submit()'
        })
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