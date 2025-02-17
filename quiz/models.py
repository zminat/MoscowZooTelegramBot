from django.db import models


class Animal(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name='Наименование животного',
        unique=True
    )
    page_url = models.URLField(
        verbose_name="Ссылка на страницу животного",
        blank=False,
        null=False
    )
    image_url = models.URLField(
        verbose_name="Ссылка на изображение",
        blank=False,
        null=False
    )

    def __str__(self):
        return self.name


class Question(models.Model):
    text = models.CharField(
        max_length=255,
        verbose_name="Текст вопроса"
    )

    def __str__(self):
        return self.text


class Answer(models.Model):
    text = models.CharField(
        max_length=255,
        verbose_name="Текст ответа"
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="answers",
        verbose_name="К какому вопросу относится"
    )
    animals = models.ManyToManyField(
        Animal,
        verbose_name='Связанные животные',
        related_name="answers"
    )

    def __str__(self):
        return self.text


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(
        "Quiz",
        on_delete=models.CASCADE,
        related_name="quiz_questions",
        verbose_name="Викторина"
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="quiz_questions",
        verbose_name="Вопрос"
    )
    order = models.PositiveIntegerField(
        verbose_name="Порядок"
    )

    class Meta:
        ordering = ["quiz", "order"]
        unique_together = [
            ("quiz", "question"),
            ("quiz", "order"),
        ]

    def __str__(self):
        return f"Викторина: {self.quiz}, Вопрос: {self.question}, Порядок: {self.order}"


class Quiz(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name="Название викторины"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
        db_index=True
    )
    questions = models.ManyToManyField(
        Question,
        through=QuizQuestion,
        related_name="quizzes",
        verbose_name="Вопросы"
    )

    def __str__(self):
        return self.name

    def get_questions_in_order(self):
        return Question.objects.filter(quiz_questions__quiz=self).order_by("quiz_questions__order")

    def save(self, *args, **kwargs):
        if self.is_active:
            Quiz.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class UserQuizAnswer(models.Model):
    telegram_user_id = models.BigIntegerField(
        verbose_name="Telegram User ID"
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        verbose_name="Викторина"
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        verbose_name="Вопрос"
    )
    answer = models.ForeignKey(
        Answer,
        on_delete=models.CASCADE,
        verbose_name="Выбранный ответ"
    )

    def __str__(self):
        return f"Пользователь {self.telegram_user_id}, Викторина {self.quiz}, Вопрос: {self.question}, Ответ: {self.answer}"
