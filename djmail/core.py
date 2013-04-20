# -*- coding: utf-8 -*-

import functools

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend
from django.core.mail import get_connection
from django.core.paginator import Paginator
from django.db import connection

from . import models

def _close_connection_on_finish(function):
    @functools.wraps(function)
    def _decorator(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            connection.close()

    return _decorator


def _get_real_backend():
    real_backend_path = getattr(settings, "DJMAIL_REAL_BACKEND",
                           'django.core.mail.backends.console.EmailBackend')
    return get_connection(backend=real_backend_path, fail_silently=True)


def _send_messages(email_messages):
    connection = _get_real_backend()

    # Create a messages on a database for correct
    # tracking of their status.
    messages = [models.Message.from_email_message(email_message, save=True)
                 for email_message in email_messages]

    # Open connection for send all messages
    connection.open()
    sended_counter = 0

    for message_model in messages:
        email = message_model.get_email_message()
        sended = connection.send_messages([email])

        if sended == 1:
            message_model.status = models.STATUS_SENT
            message_model.save()

            sended_counter += 1
        else:
            message_model.status = models.STATUS_FAILED
            message_model.save()

    connection.close()
    return sended_counter


def _retry_send_messages():
    """
    Function that retry send failed messages.
    """

    max_retry_value = getattr(settings, "DJMAIL_MAX_RETRY_NUMBER", 3)
    queryset = models.Message.objects.filter(status=models.STATUS_FAILED)\
                        .filter(retry_count__lte=max_retry_value)\
                        .order_by("-priority", "created_at")

    connection = _get_real_backend()
    paginator = Paginator(list(queryset), getattr(settings, "DJMAIL_MAX_BULK_RETRY_SEND", 10))

    for page_index in paginator.page_range:
        connection.open()
        for message_model in paginator.page(page_index).object_list:
            email = message_model.get_email_message()
            sended = connection.send_messages([email])

            if sended == 1:
                message_model.status = models.STATUS_SENT
                message_model.retry_count += 1
            else:
                message_model.retry_count += 1

            message_model.save()

        connection.close()


def _mark_discarted_messages():
    """
    Function that search messaged that exceeds the global retry
    number and marks its as discarted messages.
    """

    max_retry_value = getattr(settings, "DJMAIL_MAX_RETRY_NUMBER", 3)
    queryset = models.Message.objects.filter(status=models.STATUS_FAILED,
                                             retry_count__gt=max_retry_value)
    return queryset.update(status=models.STATUS_DISCARTED)
