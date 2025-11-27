from django.contrib import admin
from .models import Order, Notification, Worker

# -----------------------------------
# 1. ORDER ADMINI
# -----------------------------------
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 
        'customer_name', 
        'panel_kvadrat', 
        'total_price', 
        'status', 
        'created_by', 
        'created_at',
        'display_workers' # <-- Bu usul Ustalar nomini vergul bilan chiqaradi.
)
    list_filter = ('status', 'created_by')
    search_fields = ('order_number', 'customer_name')
    date_hierarchy = 'created_at' # Sana bo'yicha navigatsiya

    # ManyToMany (Ustalar) maydonini list_display'da ko'rsatish uchun usul
    def display_workers(self, obj):
        # Tayinlangan ustalar ismini vergul bilan ajratib qaytaradi
        return ", ".join([worker.user.username for worker in obj.assigned_workers.all()])
    
    display_workers.short_description = 'Tayinlangan Ustalar'


# -----------------------------------
# 2. WORKER ADMINI (Ustalar)
# -----------------------------------
@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    # display_workers da ism va rolni ko'rsatish
    list_display = ('user', 'role')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__first_name', 'role')
    # Worker yaratilganda User obyekti OneToOne bilan bog'lanadi


# -----------------------------------
# 3. NOTIFICATION ADMINI (Xabarnomalar)
# -----------------------------------
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'order', 'message', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'message', 'order__order_number')
    date_hierarchy = 'created_at'