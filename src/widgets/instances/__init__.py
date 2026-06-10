# __init__.py

from gi.repository import Adw, Gtk, GLib, Gio

import os, shutil, json, re, logging, importlib.util, threading
from ...sql_manager import generate_uuid, generate_numbered_name, prettify_model_name, Instance as SQL
from .. import dialog
from .ollama_instances import BaseInstance as BaseOllama
if os.getenv('ALPACA_OLLAMA_ONLY', '0') != '1' and importlib.util.find_spec('openai'):
    from .openai_instances import BaseInstance as BaseOpenAI
from .ollama_manager import OllamaManager

logger = logging.getLogger(__name__)

@Gtk.Template(resource_path='/com/jeffser/Alpaca/widgets/instances/preferences.ui')
class InstancePreferencesDialog(Adw.Dialog):

    __gtype_name__ = 'AlpacaInstancePreferencesDialog'

    preferences_page = Gtk.Template.Child()

    connection_group = Gtk.Template.Child()
    name_el = Gtk.Template.Child()
    port_el = Gtk.Template.Child()
    url_el = Gtk.Template.Child()
    connection_status_icon = Gtk.Template.Child()
    api_el = Gtk.Template.Child()

    tweak_group = Gtk.Template.Child()
    think_el = Gtk.Template.Child()
    expose_el = Gtk.Template.Child()
    share_name_el = Gtk.Template.Child()
    metadata_el = Gtk.Template.Child()
    self_signed_ssl_el = Gtk.Template.Child()
    max_tokens_el = Gtk.Template.Child()
    vulkan_el = Gtk.Template.Child()

    parameters_group = Gtk.Template.Child()
    override_parameters_el = Gtk.Template.Child()
    temperature_el = Gtk.Template.Child()
    seed_el = Gtk.Template.Child()
    context_size_el = Gtk.Template.Child()

    keep_alive_group = Gtk.Template.Child()
    keep_alive_selector_el = Gtk.Template.Child()
    keep_alive_minutes_el = Gtk.Template.Child()

    overrides_group = Gtk.Template.Child()
    override_0_el = Gtk.Template.Child()
    override_1_el = Gtk.Template.Child()
    override_2_el = Gtk.Template.Child()
    override_3_el = Gtk.Template.Child()

    model_group = Gtk.Template.Child()
    model_directory_el = Gtk.Template.Child()
    default_model_el = Gtk.Template.Child()
    title_model_el = Gtk.Template.Child()

    def __init__(self, instance):
        super().__init__()

        self.instance = instance
        self.set_title(_('Edit Instance') if self.instance.instance_id else _('Create Instance'))
        self.model_list = []
        self._model_list_populated = False
        self._retry_gesture = None
        self._closed = False
        self._original_url = self.instance.properties.get('url', '')
        self._original_api = self.instance.properties.get('api', '')
        self._last_committed_url = self._original_url
        self._last_committed_api = self._original_api

        # CONNECTION GROUP
        self.connection_group.set_title(self.instance.instance_type_display)
        self.connection_group.set_description(self.instance.description or self.instance.properties.get('url'))

        self.set_simple_element_value(self.name_el)
        self.set_simple_element_value(self.url_el)
        
        url_focus_ctrl = Gtk.EventControllerFocus.new()
        url_focus_ctrl.connect('leave', lambda _: self._on_connection_field_changed('url'))
        self.url_el.add_controller(url_focus_ctrl)

        if self.instance.instance_type in ('ollama', 'ollama:managed', 'openai:generic', 'llama_cpp'):
            if self.instance.instance_type == 'ollama:managed':
                try:
                    port = int(self.instance.properties.get('url').split(':')[-1])
                except:
                    port = 11435
                    
                self.port_el.connect('notify::value', lambda el, gparam: self.url_el.set_text(self.url_el.get_text().rsplit(':', 1)[0]+':{}'.format(int(el.get_value()))))
                self.expose_el.connect('notify::active', lambda el, gparam: self.url_el.set_text('http://0.0.0.0:{}'.format(int(self.port_el.get_value())) if self.expose_el.get_active() else 'http://127.0.0.1:{}'.format(int(self.port_el.get_value()))))
                
                self.port_el.set_value(port)
                self.url_el.set_visible(False)
                self.connection_status_icon.set_visible(False)
            else:
                self.port_el.set_visible(False)
        else:
            self.url_el.set_visible(False)
            self.port_el.set_visible(False)
            self.connection_status_icon.set_visible(False)

        if 'api' in self.instance.properties:
            # Set the title based on the instance type to keep the Cloudflare hint
            if self.instance.instance_type == 'cloudflare':
                normal_api_title = _('API Key (account_id:api_key)')
            else:
                normal_api_title = _('API Key (Optional)' if self.instance.instance_type == 'ollama' else _('API Key'))
            
            unchanged_api_title = _('API Key (Unchanged)')
            
            self.api_el.set_title(unchanged_api_title if self.instance.properties.get('api') else normal_api_title)
            self.api_el.connect('changed', lambda el: el.set_title(normal_api_title if el.get_text() else unchanged_api_title))

            self.set_simple_element_value(self.api_el)
            api_focus_ctrl = Gtk.EventControllerFocus.new()
            api_focus_ctrl.connect('leave', lambda _: self._on_connection_field_changed('api'))
            self.api_el.add_controller(api_focus_ctrl)

        # TWEAK GROUP
        self.set_simple_element_value(self.think_el)
        self.set_simple_element_value(self.expose_el)
        self.set_simple_element_value(self.share_name_el)
        self.set_simple_element_value(self.metadata_el)
        self.set_simple_element_value(self.self_signed_ssl_el)
        self.set_simple_element_value(self.max_tokens_el)

        # PARAMETERS GROUP
        self.set_simple_element_value(self.override_parameters_el)
        self.set_simple_element_value(self.temperature_el)
        self.set_simple_element_value(self.seed_el)
        self.set_simple_element_value(self.context_size_el)

        # KEEP ALIVE GROUP
        if 'keep_alive' in self.instance.properties:
            val = self.instance.properties.get('keep_alive', -1)
            if val > 0:
                selected_index = 0
                self.keep_alive_preset_changed(self.keep_alive_selector_el)
            elif val < 0:
                selected_index = 1
            else:
                selected_index = 2

            self.keep_alive_selector_el.set_selected(selected_index)
            self.keep_alive_selector_el.get_ancestor(Adw.PreferencesGroup).set_visible(True)

        # OVERRIDES GROUP
        for el in [self.override_0_el, self.override_1_el, self.override_2_el, self.override_3_el, self.vulkan_el]:
            self.set_simple_element_value(el)

        #MODEL GROUP
        if self.instance.instance_id:
            self.set_simple_element_value(self.model_directory_el)

            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", lambda factory, list_item: list_item.set_child(Gtk.Label(ellipsize=3, xalign=0)))
            factory.connect("bind", lambda factory, list_item: list_item.get_child().set_label(list_item.get_item().get_string()))
            self.default_model_el.set_factory(factory)
            self.title_model_el.set_factory(factory)

            self._reset_default_model()
            self._reset_title_model()

            self.default_model_el.set_visible(True)
            self.title_model_el.set_visible(True)
            self.model_group.set_visible(True)

            GLib.idle_add(self._fetch_models_async)
        else:
            self.default_model_el.set_visible(False)
            self.title_model_el.set_visible(False)

    def _on_connection_field_changed(self, field_name):
        if self._closed:
            return

        current_value = self.get_value(getattr(self, f'{field_name}_el'))
        last_committed_value = getattr(self, f'_last_committed_{field_name}')

        if current_value == last_committed_value:
            return

        setattr(self, f'_last_committed_{field_name}', current_value)

        if self._model_list_populated:
            self._retry_connection()

    def _set_connection_icon(self, state):
        self.connection_status_icon.set_visible(True)

        while self.connection_status_icon.get_first_child():
            self.connection_status_icon.remove(self.connection_status_icon.get_first_child())

        if state == 'loading':
            spinner = Gtk.Spinner()
            spinner.set_visible(True)
            spinner.start()
            self.connection_status_icon.append(spinner)
            self.connection_status_icon.set_tooltip_text(_('Checking connection…'))
        elif state == 'success':
            icon = Gtk.Image()
            icon.set_from_icon_name('check-plain-symbolic')
            icon.set_visible(True)
            self.connection_status_icon.append(icon)
            self.connection_status_icon.set_tooltip_text(_('Connection OK'))
        elif state == 'failed':
            icon = Gtk.Image()
            icon.set_from_icon_name('cross-large-symbolic')
            icon.set_visible(True)
            self.connection_status_icon.append(icon)
            self.connection_status_icon.set_tooltip_text(_('Connection failed — click to retry'))

    def _fetch_models_async(self):
        if not self.instance.instance_id or self._model_list_populated:
            return False

        GLib.idle_add(self._set_connection_icon, 'loading')

        def _thread_fetch():
            try:
                self.instance.start()
                try:
                    self.instance.client.list()
                    models = self.instance.get_local_models()
                except Exception as e:
                    models = None
                    logger.error(f"Failed to connect to Ollama: {e}")

                GLib.idle_add(self._on_models_fetched, models)
            except Exception as e:
                logger.error(e)
                GLib.idle_add(self._on_models_fetched, None)

        threading.Thread(target=_thread_fetch, daemon=True).start()
        return False

    def _on_models_fetched(self, models):
        if self._closed:
            return

        if hasattr(self, '_saved_properties'):
            for key, val in self._saved_properties.items():
                self.instance.properties[key] = val
            # Restore client: stop the one from retry attempt so next start() creates fresh connection with old properties
            self.instance.stop()
            del self._saved_properties

        if models is not None:
            self._set_connection_icon('success')
            self.model_list = models
            self._model_list_populated = True

            string_list_default = self.default_model_el.get_model()
            string_list_title = self.title_model_el.get_model()

            for model in self.model_list:
                pretty_name = prettify_model_name(model.get('name'))
                string_list_default.append(pretty_name)
                string_list_title.append(pretty_name)

            self.set_simple_element_value(self.default_model_el)
            self.set_simple_element_value(self.title_model_el)
        else:
            self._set_connection_icon('failed')
            self._model_list_populated = True
            if self._retry_gesture is None:
                self._retry_gesture = Gtk.GestureClick.new()
                self._retry_gesture.connect('released', lambda n_press, x, y, _: self._retry_connection())
                self.connection_status_icon.add_controller(self._retry_gesture)

    def _retry_connection(self):
        if self._closed:
            return

        self._model_list_populated = False

        self._saved_properties = {}
        for el in [self.url_el, self.api_el]:
            key = el.get_name()
            if key in self.instance.properties:
                self._saved_properties[key] = self.instance.properties[key]
                self.instance.properties[key] = self.get_value(el)

        self.instance.stop()
        self._reset_default_model()
        self._reset_title_model()

        self._fetch_models_async()

    def _reset_default_model(self):
        self.default_model_el.set_model(Gtk.StringList())

    def _reset_title_model(self):
        title_list = Gtk.StringList()
        title_list.append(_('Use Current Model'))
        self.title_model_el.set_model(title_list)

    def set_simple_element_value(self, el):
        if el.get_name().startswith('override:'):
            in_properties = el.get_name().removeprefix('override:') in self.instance.properties.get('overrides', {})
        else:
            in_properties = el.get_name() in self.instance.properties
        el.set_visible(in_properties)

        if in_properties:
            if el.get_name().startswith('override:'):
                value = self.instance.properties.get('overrides', {}).get(el.get_name().removeprefix('override:'))
            else:
                value = self.instance.properties.get(el.get_name())
            if el.get_name() in ('default_model', 'title_model'):
                in_properties = len(list(el.get_model())) > 0
                if isinstance(value, dict):
                    value = value.get('name')
                if value:
                    for i, model in enumerate(list(el.get_model())):
                        if model.get_string() == prettify_model_name(value):
                            el.set_selected(i)
                            break
            elif el.get_name() == 'override:OLLAMA_VULKAN':
                el.set_active(value or self.instance.properties.get('overrides', {}).get('OLLAMA_VULKAN', '0') == '1')
            elif el.get_name() == 'model_directory':
                el.set_subtitle(value)
            elif isinstance(el, Adw.ExpanderRow):
                el.set_enable_expansion(value)
            elif isinstance(el, Adw.EntryRow) and not isinstance(el, Adw.PasswordEntryRow):
                el.set_text(value)
            elif isinstance(el, Adw.SpinRow):
                el.set_value(value)
            elif isinstance(el, Adw.SwitchRow):
                el.set_active(value)
            elif isinstance(el, Adw.ComboRow):
                el.set_selected(value)

        group = el.get_ancestor(Adw.PreferencesGroup)
        if group:
            group.set_visible(group.get_visible() or in_properties)

    def get_value(self, el):
        if el.get_name() == 'default_model':
            if len(self.model_list) == 0:
                return None
            index = el.get_selected()
            if index < 0 or index >= len(self.model_list):
                return self.instance.properties.get('default_model')
            return self.model_list[index].get('name')
        elif el.get_name() == 'title_model':
            index = el.get_selected()
            if index == 0 or len(self.model_list) == 0:
                return None
            adj_index = index - 1
            if adj_index < 0 or adj_index >= len(self.model_list):
                return self.instance.properties.get('title_model')
            return self.model_list[adj_index].get('name')
        elif el.get_name() == 'model_directory':
            return el.get_subtitle()
        elif el.get_name() == 'override:OLLAMA_VULKAN':
            return '1' if el.get_active() else ''
        elif isinstance(el, Adw.PasswordEntryRow):
            return el.get_text().strip() or self.instance.properties.get(el.get_name()) or 'NOKEY'
        elif isinstance(el, Adw.ExpanderRow):
            return el.get_enable_expansion()
        elif isinstance(el, Adw.EntryRow):
            return el.get_text().strip()
        elif isinstance(el, Adw.SpinRow):
            return el.get_value()
        elif isinstance(el, Adw.SwitchRow):
            return el.get_active()
        elif isinstance(el, Adw.ComboRow):
            return el.get_selected()

    @Gtk.Template.Callback()
    def save_requested(self, button=None):
        def save_elements_values(elements:list):
            for el in elements:
                key = el.get_name()
                new_value = self.get_value(el)
                if key in self.instance.properties:
                    self.instance.properties[key] = new_value
                elif key.removeprefix('override:') in self.instance.properties.get('overrides', {}):
                    self.instance.properties['overrides'][key.removeprefix('override:')] = new_value

                if isinstance(el, Adw.ExpanderRow):
                    save_elements_values(list(list(list(list(el)[0])[1])[0]))

        for group in (self.connection_group, self.tweak_group, self.parameters_group, self.keep_alive_group, self.overrides_group, self.model_group):
            save_elements_values(list(list(list(list(group)[0])[1])[0]))

        if not self.instance.instance_id:
            self.instance.instance_id = generate_uuid()

        SQL.insert_or_update_instance(
            instance_id=self.instance.instance_id,
            pinned=self.instance.row.pinned if self.instance.row else False,
            instance_type=self.instance.instance_type,
            properties=self.instance.properties
        )

        self.instance.stop()

        if self.instance.row:
            self.instance.row.set_title(self.instance.properties.get('name'))
        else:
            row = InstanceRow(instance=self.instance)
            self.instance.row = row
            self.get_root().instance_listbox.append(row)
            self.get_root().instance_listbox.select_row(row)

        if len(list(self.get_root().instance_listbox)) > 0:
            self.get_root().instance_manager_stack.set_visible_child_name('content')
        else:
            self.get_root().instance_manager_stack.set_visible_child_name('no-instances')

        self._closed = True
        self.instance.start()

        self.close()

    @Gtk.Template.Callback()
    def keep_alive_preset_changed(self, combo, gparam=None):
        index = combo.get_selected()
        self.keep_alive_minutes_el.set_visible(index == 0)
        if index == 0:
            self.keep_alive_minutes_el.set_adjustment(Gtk.Adjustment(
                value=int(self.instance.properties.get('keep_alive', 60) / 60),
                lower=1,
                upper=1440,
                step_increment=1
            ))
        elif index == 1:
            self.keep_alive_minutes_el.set_adjustment(Gtk.Adjustment(
                value=-1,
                lower=-1,
                upper=-1,
            ))
        else:
            self.keep_alive_minutes_el.set_adjustment(Gtk.Adjustment(
                value=0,
                lower=0,
                upper=0,
            ))

    @Gtk.Template.Callback()
    def close_requested(self, button=None):
        self._closed = True
        self.instance.stop()

        if self.instance.properties.get('url', '') != self._original_url:
            self.instance.properties['url'] = self._original_url

        if self.instance.properties.get('api', '') != self._original_api:
            self.instance.properties['api'] = self._original_api

        self.close()

    @Gtk.Template.Callback()
    def model_directory_requested(self, button):
        dialog.simple_directory(
            parent = self.get_root(),
            callback = lambda res, row=self.model_directory_el: row.set_subtitle(res.get_path() if res else row.get_subtitle())
        )

    @Gtk.Template.Callback()
    def open_link(self, button):
        Gio.AppInfo.launch_default_for_uri(button.get_tooltip_text())

# Fallback for when there are no instances
class Empty:
    instance_id = ''
    instance_type = 'empty'
    instance_type_display = 'Empty'
    properties = {
        'name': _('Fallback Instance')
    }

    def stop(self):
        pass

    def get_local_models(self) -> list:
        return []

    def get_available_models(self) -> dict:
        return {}

    def get_model_info(self, model_name:str) -> dict:
        return {}

    def get_default_model(self) -> str:
        return ''

class InstanceRow(Adw.ActionRow):
    __gtype_name__ = 'AlpacaInstanceRow'

    def __init__(self, instance, pinned:bool=False):
        self.instance = instance
        self.pinned = pinned
        super().__init__(
            title = self.instance.properties.get('name'),
            subtitle = self.instance.instance_type_display,
            name = self.instance.properties.get('name'),
            visible = self.instance.instance_type != 'empty'
        )

        if self.instance.instance_type == 'ollama:managed':
            ollama_manager_button = Gtk.Button(
                tooltip_text=_('Open Ollama Manager'),
                icon_name='computer-symbolic',
                valign=3,
                css_classes=['flat']
            )
            ollama_manager_button.connect('clicked', lambda button: OllamaManager(self.instance).present(self.get_root()))
            self.add_suffix(ollama_manager_button)

        if not self.pinned:
            remove_button = Gtk.Button(
                tooltip_text=_('Remove Instance'),
                icon_name='user-trash-symbolic',
                valign=3,
                css_classes=['destructive-action', 'flat']
            )
            remove_button.connect('clicked', lambda button: dialog.simple(
                    parent = self.get_root(),
                    heading = _('Remove Instance?'),
                    body = _('Are you sure you want to remove this instance?'),
                    callback = self.remove,
                    button_name = _('Remove'),
                    button_appearance = 'destructive'
                )
            )
            self.add_suffix(remove_button)

        if not isinstance(self.instance, Empty):
            edit_button = Gtk.Button(
                tooltip_text=_('Edit Instance'),
                icon_name='edit-symbolic',
                valign=3,
                css_classes=['accent', 'flat']
            )
            edit_button.connect('clicked', lambda button: self.show_edit())
            self.add_suffix(edit_button)

    def show_edit(self):
        InstancePreferencesDialog(self.instance).present(self.get_root())

    def remove(self):
        SQL.delete_instance(self.instance.instance_id)
        if len(list(self.get_root().instance_listbox)) > 1:
            self.get_root().instance_manager_stack.set_visible_child_name('content')
        else:
            self.get_root().instance_manager_stack.set_visible_child_name('no-instances')
        self.get_parent().remove(self)

def create_instance_row(ins:dict) -> InstanceRow or None:
    if 'ollama' in ins.get('type'):
        for instance_cls in BaseOllama.__subclasses__():
            if getattr(instance_cls, 'instance_type', None) == ins.get('type'):
                return InstanceRow(
                    instance=instance_cls(
                        instance_id=ins.get('id'),
                        properties=ins.get('properties')
                    )
                )
    elif os.getenv('ALPACA_OLLAMA_ONLY', '0') != '1' and importlib.util.find_spec('openai'):
        for instance_cls in BaseOpenAI.__subclasses__():
            if getattr(instance_cls, 'instance_type', None) == ins.get('type'):
                return InstanceRow(
                    instance=instance_cls(
                        instance_id=ins.get('id'),
                        properties=ins.get('properties')
                    )
                )

def update_instance_list(instance_listbox:Gtk.ListBox, selected_instance_id:str):
    instance_listbox.remove_all()
    instances = SQL.get_instances()
    instance_added = False
    if len(instances) > 0:
        instance_listbox.get_root().instance_manager_stack.set_visible_child_name('content')
        for i, ins in enumerate(instances):
            row = create_instance_row(ins)
            if row:
                row.instance.row = row
                GLib.idle_add(instance_listbox.append, row)
                instance_added = True
                if row.instance.instance_id == selected_instance_id:
                    GLib.idle_add(instance_listbox.select_row, row)

    if not instance_added:
        GLib.idle_add(instance_listbox.get_root().instance_manager_stack.set_visible_child_name, 'no-instances')
        GLib.idle_add(instance_listbox.append, InstanceRow(Empty()))
