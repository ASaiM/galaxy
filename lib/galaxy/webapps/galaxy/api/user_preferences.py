"""
API operations on User Preferences objects.
"""

import sys
import logging

from markupsafe import escape
from sqlalchemy import false, true, or_

from galaxy import exceptions, util, web
from galaxy.managers import users
from galaxy.security.validate_user_input import validate_email
from galaxy.security.validate_user_input import validate_password
from galaxy.security.validate_user_input import validate_publicname
from galaxy.web import _future_expose_api as expose_api
from galaxy.web import _future_expose_api_anonymous as expose_api_anonymous
from galaxy.web.base.controller import BaseAPIController
from galaxy.web.base.controller import CreatesApiKeysMixin
from galaxy.web.base.controller import CreatesUsersMixin
from galaxy.web.base.controller import UsesTagsMixin
from galaxy.web.base.controller import (BaseUIController,
                                        UsesFormDefinitionsMixin)
from galaxy.web.form_builder import build_select_field, CheckboxField

log = logging.getLogger( __name__ )


class UserPreferencesAPIController( BaseAPIController, BaseUIController, UsesTagsMixin, CreatesUsersMixin, CreatesApiKeysMixin, UsesFormDefinitionsMixin ):

    @expose_api
    def index( self, trans, cntrller='user_preferences', **kwd ):
        return {'id': trans.security.encode_id( trans.user.id ),
                'message': "",
                'username': trans.user.username,
                'email': trans.user.email,
                'webapp': trans.webapp.name,
                'remote_user': trans.app.config.use_remote_user,
                'openid': trans.app.config.enable_openid,
                'enable_quotas': trans.app.config.enable_quotas,
                'disk_usage': trans.user.get_disk_usage( nice_size=True ),
                'quota': trans.app.quota_agent.get_quota( trans.user, nice_size=True ),
               }

    def __get_user_type_form_definition( self, trans, user=None, **kwd ):
        params = util.Params( kwd )
        if user and user.values:
            user_type_fd_id = trans.security.encode_id( user.values.form_definition.id )
        else:
            user_type_fd_id = params.get( 'user_type_fd_id', 'none' )
        if user_type_fd_id not in [ 'none' ]:
            user_type_form_definition = trans.sa_session.query( trans.app.model.FormDefinition ).get( trans.security.decode_id( user_type_fd_id ) )
        else:
            user_type_form_definition = None
        return user_type_form_definition

    # ===== Methods for building SelectFields  ================================
    def __build_user_type_fd_id_select_field( self, trans, selected_value ):
        # Get all the user information forms
        user_info_forms = self.get_all_forms( trans,
                                              filter=dict( deleted=False ),
                                              form_type=trans.model.FormDefinition.types.USER_INFO )
        return build_select_field( trans,
                                   objs=user_info_forms,
                                   label_attr='name',
                                   select_field_name='user_type_fd_id',
                                   initial_value='none',
                                   selected_value=selected_value,
                                   refresh_on_change=True )

    def __get_widgets( self, trans, user_type_form_definition, user=None, **kwd ):
        widgets = []
        if user_type_form_definition:
            if user:
                if user.values:
                    widgets = user_type_form_definition.get_widgets( user=user,
                                                                     contents=user.values.content,
                                                                     **kwd )
                else:
                    widgets = user_type_form_definition.get_widgets( None, contents={}, **kwd )
            else:
                widgets = user_type_form_definition.get_widgets( None, contents={}, **kwd )
        return widgets

    def user_info(self, cntrller, trans, kwd):
        '''Manage a user's login, password, public username, type, addresses, etc.'''
        params = util.Params( kwd )
        user_id = params.get( 'id', None )
        if user_id:
            user = trans.sa_session.query( trans.app.model.User ).get( trans.security.decode_id( user_id ) )
        else:
            user = trans.user
        if not user:
            raise AssertionError("The user id (%s) is not valid" % str( user_id ))
        email = util.restore_text( params.get( 'email', user.email ) )
        username = util.restore_text( params.get( 'username', '' ) )
        if not username:
            username = user.username
        message = escape( util.restore_text( params.get( 'message', '' ) ) )
        status = params.get( 'status', 'done' )
        if trans.webapp.name == 'galaxy':
            user_type_form_definition = self.__get_user_type_form_definition( trans, user=user, **kwd )
            user_type_fd_id = params.get( 'user_type_fd_id', 'none' )
            if user_type_fd_id == 'none' and user_type_form_definition is not None:
                user_type_fd_id = trans.security.encode_id( user_type_form_definition.id )
            user_type_fd_id_select_field = self.__build_user_type_fd_id_select_field( trans, selected_value=user_type_fd_id )
            widgets = self.__get_widgets( trans, user_type_form_definition, user=user, **kwd )
            # user's addresses
            show_filter = util.restore_text( params.get( 'show_filter', 'Active'  ) )
            if show_filter == 'All':
                addresses = [address for address in user.addresses]
            elif show_filter == 'Deleted':
                addresses = [address for address in user.addresses if address.deleted]
            else:
                addresses = [address for address in user.addresses if not address.deleted]
            user_info_forms = self.get_all_forms( trans,
                                                  filter=dict( deleted=False ),
                                                  form_type=trans.app.model.FormDefinition.types.USER_INFO )
            # makes the address list JSON iterable
            address_list = dict()
            index_add = 0
            for item in addresses:
                address_list[index_add] = dict()
                address_list[index_add]["desc"] = item.desc
                address_list[index_add]["html"] = item.get_html()
                address_list[index_add]["deleted"] = item.deleted
                address_list[index_add]["address_id"] = trans.security.encode_id(item.id)
                index_add = index_add + 1
    
            # makes the widget list JSON iterable
            widget_list = dict()
            index_widget = 0
            for item in widgets:
                widget_list[index_widget] = dict()
                widget_list[index_widget]["label"] = item['label']
                widget_list[index_widget]["html"] = item['widget'].get_html()
                widget_list[index_widget]["helptext"] = item['helptext']
                index_widget = index_widget + 1

            return {'cntrller': cntrller,
                    'webapp': trans.webapp.name,
                    'user_id': trans.security.encode_id( trans.user.id ),
                    'is_admin': trans.user_is_admin(),
                    'values': user.values,
                    'email': email,
                    'username': username,
                    'user_type_fd_id_select_field_options': user_type_fd_id_select_field.options,
                    'user_type_fd_id_select_html': user_type_fd_id_select_field.get_html(),
                    'user_info_forms': user_info_forms,
                    'user_type_form_definition': user_type_form_definition,
                    'user_type_fd_id': user_type_fd_id,
                    'user_type_fd_id_encoded': trans.security.encode_id( user_type_fd_id ),
                    'widgets': widget_list,
                    'addresses' : address_list,
                    'show_filter': show_filter,
                    'message': message,
                    'status': status
                   }
        else:
            return {'cntrller': cntrller,
                    'webapp': trans.webapp.name,
                    'user_id': trans.security.encode_id( trans.user.id ),
                    'is_admin': trans.user_is_admin(),
                    'active_repositories': user.active_repositories,
                    'email': email,
                    'username': username,
                    'message': message,
                    'status': status
                   }

    @expose_api
    def manage_user_info( self, trans, cntrller='user_preferences', **kwd ):
        """ Manage User Info API call """
        return self.user_info(cntrller, trans, kwd)

    @expose_api
    def edit_info( self, trans, cntrller='user_preferences', **kwd ):
        """
        API call for Edit user information = username, email or password.
        """
        params = util.Params( kwd )
        is_admin = cntrller == 'admin' and trans.user_is_admin()
        message = util.restore_text( params.get( 'message', ''  ) )
        status = params.get( 'status', 'done' )
        user_id = params.get( 'user_id', None )
        button_type = params.get( 'button_name', None )
        
        if user_id and is_admin:
            user = trans.sa_session.query( trans.app.model.User ).get( trans.security.decode_id( user_id ) )
        elif user_id and ( not trans.user or trans.user.id != trans.security.decode_id( user_id ) ):
            message = 'Invalid user id'
            status = 'error'
            user = None
        else:
            user = trans.user
        if user and (button_type == 'login_info_button'):
            # Editing email and username
            email = util.restore_text( params.get( 'email', '' ) )
            username = util.restore_text( params.get( 'username', '' ) ).lower()

            # Validate the new values for email and username
            message = validate_email( trans, email, user )
            if not message and username:
                message = validate_publicname( trans, username, user )
            if message:
                status = 'error'
            else:
                if ( user.email != email ):
                    # The user's private role name must match the user's login ( email )
                    private_role = trans.app.security_agent.get_private_user_role( user )
                    private_role.name = email
                    private_role.description = 'Private role for ' + email
                    # Change the email itself
                    user.email = email
                    trans.sa_session.add_all( ( user, private_role ) )
                    trans.sa_session.flush()
                    if trans.webapp.name == 'galaxy' and trans.app.config.user_activation_on:
                        user.active = False
                        trans.sa_session.add( user )
                        trans.sa_session.flush()
                        is_activation_sent = self.send_verification_email( trans, user.email, user.username )
                        if is_activation_sent:
                            message = 'The login information has been updated with the changes.<br>Verification email has been sent to your new email address. Please verify it by clicking the activation link in the email.<br>Please check your spam/trash folder in case you cannot find the message.'
                        else:
                            message = 'Unable to send activation email, please contact your local Galaxy administrator.'
                            if trans.app.config.error_email_to is not None:
                                message += ' Contact: %s' % trans.app.config.error_email_to
                if ( user.username != username ):
                    user.username = username
                    trans.sa_session.add( user )
                    trans.sa_session.flush()
                message = 'The login information has been updated with the changes.'
        elif user and (button_type == 'edit_user_info_button'):
            # Edit user information - webapp MUST BE 'galaxy'
            user_type_fd_id = params.get( 'user_type_fd_id', 'none' )
            if user_type_fd_id not in [ 'none' ]:
                user_type_form_definition = trans.sa_session.query( trans.app.model.FormDefinition ).get( trans.security.decode_id( user_type_fd_id ) )
            elif user.values:
                user_type_form_definition = user.values.form_definition
            else:
                # User was created before any of the user_info forms were created
                user_type_form_definition = None
            if user_type_form_definition:
                values = self.get_form_values( trans, user, user_type_form_definition, **kwd )
            else:
                values = {}
            flush_needed = False
            if user.values:
                # Editing the user info of an existing user with existing user info
                user.values.content = values
                trans.sa_session.add( user.values )
                flush_needed = True
            elif values:
                form_values = trans.model.FormValues( user_type_form_definition, values )
                trans.sa_session.add( form_values )
                user.values = form_values
                flush_needed = True
            if flush_needed:
                trans.sa_session.add( user )
                trans.sa_session.flush()
            message = "The user information has been updated with the changes."
        if user and trans.webapp.name == 'galaxy' and is_admin:
            kwd[ 'user_id' ] = trans.security.encode_id( user.id )
        kwd[ 'id' ] = user_id
        if message:
            kwd[ 'message' ] = util.sanitize_text( message )
        if status:
            kwd[ 'status' ] = status

        # makes a call to manage user info method
        return self.user_info(cntrller, trans, kwd)