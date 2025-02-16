from django.contrib import admin
from django.utils.html import mark_safe
from .models import Animal, Question, Answer, QuizQuestion, Quiz


@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'page_link', 'image_preview')

    def page_link(self, obj):
        return mark_safe(f'<a href="{obj.page_url}" target="_blank">{obj.name}</a>')

    page_link.short_description = "Страница животного"

    def image_preview(self, obj):
        return mark_safe(f'<img src="{obj.image_url}" width="100" style="object-fit: contain;" />')

    image_preview.short_description = "Изображение"


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 4
    fields = ("text", "animals")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "text", "answers_list")
    inlines = [AnswerInline]

    def answers_list(self, obj):
        return ", ".join(answer.text for answer in obj.answers.all())

    answers_list.short_description = "Ответы"


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ('id', 'text', 'animals_list')

    def animals_list(self, obj):
        return ", ".join([animal.name for animal in obj.animals.all()])

    animals_list.short_description = "Связанные животные"


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "question", "order")


class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 1
    fields = ("question", "order")


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "questions_list")
    inlines = [QuizQuestionInline]

    def questions_list(self, obj):
        questions = obj.get_questions_in_order()
        return ", ".join(q.text for q in questions)

    questions_list.short_description = "Вопросы"
