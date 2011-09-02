from copy import deepcopy
from django.conf import settings
from django.contrib.admin.widgets import AdminSplitDateTime, AdminDateWidget
from django.forms.models import modelform_factory
from django.forms.widgets import FileInput
from django.template.loader import render_to_string
from django.utils import simplejson
from django.utils.importlib import import_module
from django.utils.translation import ugettext

from inplaceeditform.commons import has_transmeta, apply_filters


class BaseAdaptorField(object):

    def __init__(self, request, obj, field_name,
                       filters_to_show=None,
                       config=None):
        self.request = request
        self.obj = obj
        self.field_name = field_name
        self.filters_to_show = filters_to_show and filters_to_show.split('|')

        self.model = obj.__class__
        self.field_name_render = field_name  # To transmeta

        self.config = config or {}
        self.config['obj_id'] = self.obj.id
        self.config['field_name'] = self.field_name_render
        self.config['filters_to_show'] = self.filters_to_show
        self.config['app_label'] = self.model._meta.app_label
        self.config['module_name'] = self.model._meta.module_name
        self.config['filters_to_show'] = filters_to_show

        filters_to_edit = self.config.get('filters_to_edit', None)
        self.filters_to_edit = filters_to_edit and filters_to_edit.split('|') or []

        self.class_inplace = self.config.get('class_inplace', '')
        self.tag_name_cover = self.config.get('tag_name_cover', 'span')
        font_size = self.config.get('font_size', '12')
        if font_size.endswith('px'):
            self.font_size = int(font_size.replace('px', ''))
        else:
            self.font_size = 12
        loads = self.config.get('loads', None)
        self.loads = loads and loads.split(':') or []
        self.initial = {}
        self._transmeta_processing()

    @property
    def name(self):
        return ''

    @property
    def classes(self):
        return 'inplaceedit %sinplaceedit' % (self.name)

    @classmethod
    def get_config(self, **kwargs):
        return kwargs

    def get_form_class(self):
        return modelform_factory(self.model)

    def get_form(self):
        form_class = self.get_form_class()
        return form_class(instance=self.obj,
                          initial=self.initial,
                          prefix=id(form_class))

    def get_field(self):
        field = self.get_form()[self.field_name]
        field = self._adding_size(field)
        return field

    def get_value_editor(self, value):
        return self.get_field().field.clean(value)

    def render_value(self, field_name=None):
        field_name = field_name or self.field_name_render
        value = getattr(self.obj, field_name)
        if callable(value):
            value = value()
        return apply_filters(value, self.filters_to_show, self.loads)

    def render_value_edit(self):
        value = self.render_value()
        if value:
            return value
        return self.empty_value()

    def empty_value(self):
        return ugettext('Dobleclick to edit')

    def render_field(self, template_name="inplaceeditform/render_field.html", extra_context=None):
        extra_context = extra_context or {}
        context = {'form': self.get_form(),
                   'field': self.get_field(),
                   'MEDIA_URL': settings.MEDIA_URL,
                   'class_inplace': self.class_inplace}
        context.update(extra_context)
        return render_to_string(template_name, context)

    def render_media_field(self, template_name="inplaceeditform/render_media_field.html", extra_context=None):
        extra_context = extra_context or {}
        context = {'field': self.get_field(),
                   'MEDIA_URL': settings.MEDIA_URL,
                   'ADMIN_MEDIA_PREFIX': settings.ADMIN_MEDIA_PREFIX}
        context.update(extra_context)

        return render_to_string(template_name, context)

    def render_config(self, template_name="inplaceeditform/render_config.html"):
        return render_to_string(template_name,
                                {'config': self.config})

    def can_edit(self):
        can_edit_adaptor_path = getattr(settings, 'ADAPTOR_INPLACEEDIT_EDIT', None)
        if can_edit_adaptor_path:
            path_module, class_adaptor = ('.'.join(can_edit_adaptor_path.split('.')[:-1]),
                                          can_edit_adaptor_path.split('.')[-1])
            return getattr(import_module(path_module), class_adaptor).can_edit(self)
        model_edit = '%s.change_%s' % (self.model._meta.app_label,self.model._meta.module_name)
        if self.request.user.has_perm(model_edit):
            return True
        return self.request.user.is_authenticated and self.request.user.is_superuser

    def loads_to_post(self, request):
        return simplejson.loads(request.POST.get('value'))

    def save(self, value):
        setattr(self.obj, self.field_name, value)
        self.obj.save()

    def get_auto_height(self):
        return self.config.get('auto_height', False)

    def get_auto_width(self):
        return self.config.get('auto_width', False)

    def treatment_height(self, height, width=None):
        return "%spx" % height

    def treatment_width(self, width, height=None):
        return "%spx" % width

    def _adding_size(self, field):
        attrs = field.field.widget.attrs
        widget_options = self.config and self.config.get('widget_options', {})
        auto_height = self.get_auto_height()
        auto_width = self.get_auto_width()
        if not 'style' in attrs:
            style = ''
            height = int(widget_options.get('height', '0').replace('px', ''))
            width = int(widget_options.get('width', '0').replace('px', ''))
            if height and not auto_height:
                style += "height: %s; " % self.treatment_height(height, width)
            if width and not auto_width:
                style += "width: %s; " % self.treatment_width(width, height)
            if not auto_height or not auto_width:
                style += "font-size: %spx; " % self.font_size
            for key, value in widget_options.items():
                if key in ('height', 'width'):
                    continue
                style += "%s: %s; " % (key, value)
            attrs['style'] = style
        field.field.widget.attrs = attrs
        return field

    def _transmeta_processing(self):
        if has_transmeta:
            import transmeta
            translatable_fields = self._get_translatable_fields(self.model)
            if self.field_name in translatable_fields:
                self.field_name = transmeta.get_real_fieldname(self.field_name)
                self.transmeta = True
                if not self.render_value(self.field_name):
                    self.initial = {self.field_name: ugettext('Write a traslation')}
                return
        self.transmeta = False

    def _get_translatable_fields(self, cls):
        classes = cls.mro()
        translatable_fields = []
        [translatable_fields.extend(cl._meta.translatable_fields) for cl in classes \
                                    if getattr(cl, '_meta', None) and getattr(cl._meta, 'translatable_fields', None)]
        return translatable_fields


class AdaptorTextField(BaseAdaptorField):

    INCREASE_HEIGHT = 3
    MULTIPLIER_WIDTH = 1.25

    @property
    def name(self):
        return 'text'

    def treatment_height(self, height, width=None):
        return "%spx" % (self.font_size + self.INCREASE_HEIGHT)

    def treatment_width(self, width, height=None):
        return "%spx" % (width * self.MULTIPLIER_WIDTH)


class AdaptorTextAreaField(BaseAdaptorField):

    @property
    def name(self):
        return 'textarea'

    @property
    def classes(self):
        return "textareainplaceedit %s" % super(AdaptorTextAreaField, self).classes


class AdaptorBooleanField(BaseAdaptorField):

    @property
    def name(self):
        return 'boolean'

    def render_value(self, field_name=None, template_name="inplaceeditform/adaptor_boolean/render_value.html"):
        value = super(AdaptorBooleanField, self).render_value(field_name)
        return render_to_string(template_name, {'value': value, 'MEDIA_URL': settings.MEDIA_URL})

    def render_field(self, template_name="inplaceeditform/adaptor_boolean/render_field.html"):
        return super(AdaptorBooleanField, self).render_field(template_name)

    def render_media_field(self, template_name="inplaceeditform/adaptor_boolean/render_media_field.html"):
        return super(AdaptorBooleanField, self).render_media_field(template_name)


class BaseDateField(BaseAdaptorField):

    def render_media_field(self, template_name="inplaceeditform/adaptor_date/render_media_field.html"):
        return super(BaseDateField, self).render_media_field(template_name)


class AdaptorDateField(BaseDateField):

    @property
    def name(self):
        return 'date'

    def render_field(self, template_name="inplaceeditform/adaptor_date/render_field.html"):
        return super(AdaptorDateField, self).render_field(template_name)

    def get_field(self):
        field = super(AdaptorDateField, self).get_field()
        field.field.widget = AdminDateWidget()
        return field

    def render_value(self, field_name=None):
        val = super(AdaptorDateField, self).render_value(field_name)
        if not isinstance(val, str) and not isinstance(val, unicode):
            val = apply_filters(val, ["date:'%s'" % settings.DATE_FORMAT])
        return val


class AdaptorDateTimeField(BaseDateField):

    @property
    def name(self):
        return 'datetime'

    def render_field(self, template_name="inplaceeditform/adaptor_datetime/render_field.html"):
        return super(AdaptorDateTimeField, self).render_field(template_name)

    def render_media_field(self, template_name="inplaceeditform/adaptor_datetime/render_media_field.html"):
        return super(AdaptorDateTimeField, self).render_media_field(template_name)

    def get_field(self):
        field = super(AdaptorDateTimeField, self).get_field()
        field.field.widget = AdminSplitDateTime()
        return field

    def render_value(self, field_name=None):
        val = super(AdaptorDateTimeField, self).render_value(field_name)
        if not isinstance(val, str) and not isinstance(val, unicode):
            val = apply_filters(val, ["date:'%s'" % settings.DATETIME_FORMAT])
        return val


class AdaptorChoicesField(BaseAdaptorField):

    MULTIPLIER_HEIGHT = 1.5
    INCREASE_WIDTH = 40

    @property
    def name(self):
        return 'choices'

    def treatment_height(self, height, width=None):
        return "%spx" % int(self.font_size * self.MULTIPLIER_HEIGHT)

    def treatment_width(self, width, height=None):
        return "%spx" % (width + self.INCREASE_WIDTH)

    def render_value(self, field_name=None):
        field_name = field_name or self.field_name
        return super(AdaptorChoicesField, self).render_value('get_%s_display' % field_name)


class AdaptorForeingKeyField(BaseAdaptorField):

    MULTIPLIER_HEIGHT = 1.5
    INCREASE_WIDTH = 40

    @property
    def name(self):
        return 'fk'

    def treatment_height(self, height, width=None):
        return "%spx" % int(self.font_size * self.MULTIPLIER_HEIGHT)

    def treatment_width(self, width, height=None):
        return "%spx" % (width + self.INCREASE_WIDTH)

    def render_value(self, field_name=None):
        value = super(AdaptorForeingKeyField, self).render_value(field_name)
        value = getattr(value, '__unicode__', None) and value.__unicode__() or None
        return value

    def get_value_editor(self, value):
        value = super(AdaptorForeingKeyField, self).get_value_editor(value)
        return value and value.pk

    def save(self, value):
        setattr(self.obj, "%s_id" % self.field_name, value)
        self.obj.save()


class AdaptorManyToManyField(BaseAdaptorField):

    MULTIPLIER_HEIGHT = 6
    INCREASE_WIDTH = 50

    @property
    def name(self):
        return 'm2m'

    def treatment_height(self, height, width=None):
        return "%spx" % (self.font_size * self.MULTIPLIER_HEIGHT)

    def treatment_width(self, width, height=None):
        return "%spx" % (width + self.INCREASE_WIDTH)

    def get_value_editor(self, value):
        return [item.pk for item in super(AdaptorManyToManyField, self).get_value_editor(value)]

    def render_value(self, field_name=None):
        return super(AdaptorManyToManyField, self).render_value(field_name).all()


class AdaptorCommaSeparatedManyToManyField(AdaptorManyToManyField):

    @property
    def name(self):
        return 'm2mcomma'

    def render_value(self, field_name=None, template_name="inplaceeditform/adaptor_m2m/render_commaseparated_value.html"):
        queryset = super(AdaptorCommaSeparatedManyToManyField, self).render_value(field_name)
        return render_to_string(template_name, {'queryset': queryset})


class AdaptorFileField(BaseAdaptorField):

    MULTIPLIER_HEIGHT = 2

    def __init__(self, *args, **kwargs):
        super(AdaptorFileField, self).__init__(*args, **kwargs)
        self.config['send_csrfToken'] = 1

    def loads_to_post(self, request):
        files = request.FILES.values()
        return files and files[0] or None

    def treatment_height(self, height, width=None):
        return "%spx" % (self.font_size * self.MULTIPLIER_HEIGHT)

    def render_field(self, template_name="inplaceeditform/adaptor_file/render_field.html"):
        from django.core.context_processors import csrf
        extra_context = csrf(self.request)
        return super(AdaptorFileField, self).render_field(template_name, extra_context)

    def render_media_field(self, template_name="inplaceeditform/adaptor_file/render_media_field.html"):
        return super(AdaptorFileField, self).render_media_field(template_name)

    def render_value(self, field_name=None, template_name='inplaceeditform/adaptor_file/render_value.html'):
        field_name = field_name or self.field_name_render
        value = getattr(self.obj, field_name)
        if not value:
            return ''
        config = deepcopy(self.config)
        context = {'value': value,
                   'obj': self.obj}
        config.update(context)
        return render_to_string(template_name, config)


class AdaptorImageField(AdaptorFileField):

    def get_field(self):
        field = super(AdaptorImageField, self).get_field()
        field.field.widget = FileInput()
        return field

    def render_field(self, template_name="inplaceeditform/adaptor_image/render_field.html"):
        return super(AdaptorImageField, self).render_field(template_name)

    def render_media_field(self, template_name="inplaceeditform/adaptor_image/render_media_field.html"):
        return super(AdaptorImageField, self).render_media_field(template_name)

    def render_value(self, field_name=None, template_name='inplaceeditform/adaptor_image/render_value.html'):
        return super(AdaptorImageField, self).render_value(field_name=field_name, template_name=template_name)
