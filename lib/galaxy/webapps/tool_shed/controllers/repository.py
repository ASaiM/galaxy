import logging
import os
import string
import tempfile
from time import gmtime
from time import strftime
from datetime import date

from galaxy import util
from galaxy import web
from galaxy.web.base.controller import BaseUIController
from galaxy.web.form_builder import CheckboxField
from galaxy.web.framework.helpers import grids
from galaxy.util import json
from galaxy.model.orm import and_

from tool_shed.capsule import capsule_manager
from tool_shed.dependencies.repository import relation_builder

from tool_shed.util.web_util import escape
from tool_shed.galaxy_install import dependency_display
from tool_shed.metadata import repository_metadata_manager
from tool_shed.utility_containers import ToolShedUtilityContainerManager

from tool_shed.tools import tool_validator
from tool_shed.tools import tool_version_manager

from tool_shed.util import basic_util
from tool_shed.util import common_util
from tool_shed.util import encoding_util
from tool_shed.util import hg_util
from tool_shed.util import metadata_util
from tool_shed.util import readme_util
from tool_shed.util import repository_util
from tool_shed.util import search_util
from tool_shed.util import shed_util_common as suc
from tool_shed.util import tool_util
from tool_shed.util import workflow_util

from galaxy.webapps.tool_shed.util import ratings_util

import tool_shed.grids.repository_grids as repository_grids
import tool_shed.grids.util as grids_util

import tool_shed.repository_types.util as rt_util

from galaxy import eggs
eggs.require( 'mercurial' )

from mercurial import mdiff
from mercurial import patch

log = logging.getLogger( __name__ )

malicious_error = "  This changeset cannot be downloaded because it potentially produces malicious behavior or contains inappropriate content."
malicious_error_can_push = "  Correct this changeset as soon as possible, it potentially produces malicious behavior or contains inappropriate content."


class RepositoryController( BaseUIController, ratings_util.ItemRatings ):

    category_grid = repository_grids.CategoryGrid()
    datatypes_grid = repository_grids.DatatypesGrid()
    deprecated_repositories_i_own_grid = repository_grids.DeprecatedRepositoriesIOwnGrid()
    email_alerts_repository_grid = repository_grids.EmailAlertsRepositoryGrid()
    docker_image_grid = repository_grids.DockerImageGrid()
    install_matched_repository_grid = repository_grids.InstallMatchedRepositoryGrid()
    matched_repository_grid = repository_grids.MatchedRepositoryGrid()
    my_writable_repositories_grid = repository_grids.MyWritableRepositoriesGrid()
    my_writable_repositories_missing_tool_test_components_grid = repository_grids.MyWritableRepositoriesMissingToolTestComponentsGrid()
    my_writable_repositories_with_failing_tool_tests_grid = repository_grids.MyWritableRepositoriesWithFailingToolTestsGrid()
    my_writable_repositories_with_invalid_tools_grid = repository_grids.MyWritableRepositoriesWithInvalidToolsGrid()
    my_writable_repositories_with_no_failing_tool_tests_grid = repository_grids.MyWritableRepositoriesWithNoFailingToolTestsGrid()
    my_writable_repositories_with_skip_tests_checked_grid = repository_grids.MyWritableRepositoriesWithSkipTestsCheckedGrid()
    my_writable_repositories_with_test_install_errors_grid = repository_grids.MyWritableRepositoriesWithTestInstallErrorsGrid()
    repositories_by_user_grid = repository_grids.RepositoriesByUserGrid()
    repositories_i_own_grid = repository_grids.RepositoriesIOwnGrid()
    repositories_i_can_administer_grid = repository_grids.RepositoriesICanAdministerGrid()
    repositories_in_category_grid = repository_grids.RepositoriesInCategoryGrid()
    repositories_missing_tool_test_components_grid = repository_grids.RepositoriesMissingToolTestComponentsGrid()
    repositories_with_failing_tool_tests_grid = repository_grids.RepositoriesWithFailingToolTestsGrid()
    repositories_with_invalid_tools_grid = repository_grids.RepositoriesWithInvalidToolsGrid()
    repositories_with_no_failing_tool_tests_grid = repository_grids.RepositoriesWithNoFailingToolTestsGrid()
    repositories_with_skip_tests_checked_grid = repository_grids.RepositoriesWithSkipTestsCheckedGrid()
    repositories_with_test_install_errors_grid = repository_grids.RepositoriesWithTestInstallErrorsGrid()
    repository_dependencies_grid = repository_grids.RepositoryDependenciesGrid()
    repository_grid = repository_grids.RepositoryGrid()
    # The repository_metadata_grid is not currently displayed, but is sub-classed by several grids.
    repository_metadata_grid = repository_grids.RepositoryMetadataGrid()
    tool_dependencies_grid = repository_grids.ToolDependenciesGrid()
    tools_grid = repository_grids.ToolsGrid()
    valid_category_grid = repository_grids.ValidCategoryGrid()
    valid_repository_grid = repository_grids.ValidRepositoryGrid()

    @web.expose
    def browse_categories( self, trans, **kwd ):
        # The request came from the tool shed.
        if 'f-free-text-search' in kwd:
            # Trick to enable searching repository name, description from the CategoryGrid.
            # What we've done is rendered the search box for the RepositoryGrid on the grid.mako
            # template for the CategoryGrid.  See ~/templates/webapps/tool_shed/category/grid.mako.
            # Since we are searching repositories and not categories, redirect to browse_repositories().
            if 'id' in kwd and 'f-free-text-search' in kwd and kwd[ 'id' ] == kwd[ 'f-free-text-search' ]:
                # The value of 'id' has been set to the search string, which is a repository name.
                # We'll try to get the desired encoded repository id to pass on.
                try:
                    repository_name = kwd[ 'id' ]
                    repository = suc.get_repository_by_name( trans.app, repository_name )
                    kwd[ 'id' ] = trans.security.encode_id( repository.id )
                except:
                    pass
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              **kwd ) )
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation in [ "repositories_by_category", "repositories_by_user" ]:
                # Eliminate the current filters if any exist.
                for k, v in kwd.items():
                    if k.startswith( 'f-' ):
                        del kwd[ k ]
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories',
                                                                  **kwd ) )
        title = trans.app.repository_grid_filter_manager.get_grid_title( trans,
                                                                         trailing_string='by Category',
                                                                         default='Repositories' )
        self.category_grid.title = title
        return self.category_grid( trans, **kwd )

    @web.expose
    def browse_datatypes( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            # The received id is a RepositoryMetadata id.
            repository_metadata_id = kwd[ 'id' ]
            repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, repository_metadata_id )
            repository_id = trans.security.encode_id( repository_metadata.repository_id )
            changeset_revision = repository_metadata.changeset_revision
            new_kwd = dict( id=repository_id,
                            changeset_revision=changeset_revision )
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **new_kwd ) )
        return self.datatypes_grid( trans, **kwd )

    @web.expose
    def browse_deprecated_repositories_i_own( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              operation='view_or_manage_repository',
                                                              id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        return self.deprecated_repositories_i_own_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              operation='view_or_manage_repository',
                                                              id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        return self.my_writable_repositories_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories_missing_tool_test_components( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>you are authorized to update them</li>'
            message += '<li>the latest installable revision contains at least 1 tool with no defined tests <b>OR</b>:</li>'
            message += '<li>the latest installable revision contains at least 1 tool with a test that requires a missing test data file</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.my_writable_repositories_missing_tool_test_components_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories_with_failing_tool_tests( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>you are authorized to update them</li>'
            message += '<li>the latest installable revision contains at least 1 tool</li>'
            message += '<li>the latest installable revision is not missing any tool test components</li>'
            message += '<li>the latest installable revision has no installation errors</li>'
            message += '<li>the latest installable revision has at least 1 tool test that fails</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.my_writable_repositories_with_failing_tool_tests_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories_with_invalid_tools( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>you are authorized to update them</li>'
            message += '<li>the latest metadata revision contains at least 1 invalid tool</li>'
            message += '</ul>'
            message += 'Click the tool config file name to see why the tool is invalid.'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.my_writable_repositories_with_invalid_tools_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories_with_no_failing_tool_tests( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>you are authorized to update them</li>'
            message += '<li>the latest installable revision contains at least 1 tool</li>'
            message += '<li>the latest installable revision is not missing any tool test components</li>'
            message += '<li>the latest installable revision has no tool tests that fail</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.my_writable_repositories_with_no_failing_tool_tests_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories_with_install_errors( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>you are authorized to update them</li>'
            message += '<li>the latest installable revision is not missing any tool test components</li>'
            message += '<li>the latest installable revision has installation errors (the repository itself, '
            message += 'repository dependencies or tool dependencies)</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.my_writable_repositories_with_test_install_errors_grid( trans, **kwd )

    @web.expose
    def browse_my_writable_repositories_with_skip_tool_test_checked( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>you are authorized to update them</li>'
            message += '<li>the latest installable revision has <b>Skip automated testing of tools in this '
            message += 'revision</b> checked if the repository type is <b>Unrestricted</b> or <b>Skip '
            message += 'automated testing of this tool dependency recipe</b> checked if the repository '
            message += 'type is <b>Tool dependency definition</b></li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.my_writable_repositories_with_skip_tests_checked_grid( trans, **kwd )

    @web.expose
    def browse_repositories( self, trans, **kwd ):
        # We add params to the keyword dict in this method in order to rename the param with an "f-" prefix,
        # simulating filtering by clicking a search link.  We have to take this approach because the "-"
        # character is illegal in HTTP requests.
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "edit_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='edit_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation == "reviewed_repositories_i_own":
                return trans.response.send_redirect( web.url_for( controller='repository_review',
                                                                  action='reviewed_repositories_i_own' ) )
            elif operation == "repositories_by_category":
                category_id = kwd.get( 'id', None )
                message = escape( kwd.get( 'message', '' ) )
                status = kwd.get( 'status', 'done' )
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_in_category',
                                                                  id=category_id,
                                                                  message=message,
                                                                  status=status ) )
            elif operation == "receive email alerts":
                if trans.user:
                    if kwd[ 'id' ]:
                        kwd[ 'caller' ] = 'browse_repositories'
                        return trans.response.send_redirect( web.url_for( controller='repository',
                                                                          action='set_email_alerts',
                                                                          **kwd ) )
                else:
                    kwd[ 'message' ] = 'You must be logged in to set email alerts.'
                    kwd[ 'status' ] = 'error'
                    del kwd[ 'operation' ]
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              operation='view_or_manage_repository',
                                                              id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        title = trans.app.repository_grid_filter_manager.get_grid_title( trans,
                                                                         trailing_string='',
                                                                         default='Repositories' )
        self.repository_grid.title = title
        return self.repository_grid( trans, **kwd )

    @web.expose
    def browse_repositories_by_user( self, trans, **kwd ):
        """Display the list of repositories owned by a specified user."""
        # Eliminate the current search filters if any exist.
        for k, v in kwd.items():
            if k.startswith( 'f-' ):
                del kwd[ k ]
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
        user_id = kwd.get( 'user_id', None )
        if user_id is None:
            # The received id is the repository id, so we need to get the id of the user that owns the repository.
            repository_id = kwd.get( 'id', None )
            if repository_id:
                repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
                user_id = trans.security.encode_id( repository.user.id )
                kwd[ 'user_id' ] = user_id
            else:
                # The user selected a repository revision which results in a refresh_on_change.
                selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
                if repository:
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action='view_or_manage_repository',
                                                                      id=trans.security.encode_id( repository.id ),
                                                                      changeset_revision=selected_changeset_revision ) )
        if user_id:
            user = suc.get_user( trans.app, user_id )
            trailing_string = ''
            default = 'Repositories Owned by %s' % str( user.username )
        else:
            trailing_string = ''
            default = 'Repositories'
        title = trans.app.repository_grid_filter_manager.get_grid_title( trans,
                                                                         trailing_string=trailing_string,
                                                                         default=default )
        self.repositories_by_user_grid.title = title
        return self.repositories_by_user_grid( trans, **kwd )

    @web.expose
    def browse_repositories_i_can_administer( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              operation='view_or_manage_repository',
                                                              id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        return self.repositories_i_can_administer_grid( trans, **kwd )

    @web.expose
    def browse_repositories_i_own( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              operation='view_or_manage_repository',
                                                              id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        return self.repositories_i_own_grid( trans, **kwd )

    @web.expose
    def browse_repositories_in_category( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            if operation == 'repositories_by_user':
                user_id = kwd.get( 'user_id', None )
                if user_id is None:
                    # The received id is the repository id, so we need to get the id of the user that owns the repository.
                    repository_id = kwd.get( 'id', None )
                    if repository_id:
                        repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
                        user_id = trans.security.encode_id( repository.user.id )
                        user = suc.get_user( trans.app, user_id )
                        self.repositories_by_user_grid.title = "Repositories owned by %s" % user.username
                        kwd[ 'user_id' ] = user_id
                        return self.repositories_by_user_grid( trans, **kwd )
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            # The user selected a repository revision which results in a refresh_on_change.
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='view_or_manage_repository',
                                                              id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        category_id = kwd.get( 'id', None )
        if category_id:
            category = suc.get_category( trans.app, category_id )
            if category:
                trailing_string = 'in Category %s' % str( category.name )
            else:
                trailing_string = 'in Category'
        else:
            trailing_string = 'in Category'
        title = trans.app.repository_grid_filter_manager.get_grid_title( trans,
                                                                         trailing_string=trailing_string,
                                                                         default='Repositories' )
        self.repositories_in_category_grid.title = title
        return self.repositories_in_category_grid( trans, **kwd )

    @web.expose
    def browse_repositories_missing_tool_test_components( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>the latest installable revision contains at least 1 tool with no defined tests <b>OR</b>:</li>'
            message += '<li>the latest installable revision contains at least 1 tool with a test that requires a missing test data file</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.repositories_missing_tool_test_components_grid( trans, **kwd )

    @web.expose
    def browse_repositories_with_failing_tool_tests( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>the latest installable revision contains at least 1 tool</li>'
            message += '<li>the latest installable revision is not missing any tool test components</li>'
            message += '<li>the latest installable revision has at least 1 tool test that fails</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.repositories_with_failing_tool_tests_grid( trans, **kwd )

    @web.expose
    def browse_repositories_with_install_errors( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>the latest installable revision is not missing any tool test components</li>'
            message += '<li>the latest installable revision has installation errors (the repository itself, '
            message += 'repository dependencies or tool dependencies)</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.repositories_with_test_install_errors_grid( trans, **kwd )

    @web.expose
    def browse_repositories_with_invalid_tools( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>the latest metadata revision contains at least 1 invalid tool</li>'
            message += '</ul>'
            message += 'Click the tool config file name to see why the tool is invalid.'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.repositories_with_invalid_tools_grid( trans, **kwd )

    @web.expose
    def browse_repositories_with_no_failing_tool_tests( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>the latest installable revision contains at least 1 tool</li>'
            message += '<li>the latest installable revision is not missing any tool test components</li>'
            message += '<li>the latest installable revision has no tool tests that fail</li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.repositories_with_no_failing_tool_tests_grid( trans, **kwd )

    @web.expose
    def browse_repositories_with_skip_tool_test_checked( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
            elif operation == "repositories_by_user":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repositories_by_user',
                                                                  **kwd ) )
            elif operation in [ 'mark as deprecated', 'mark as not deprecated' ]:
                kwd[ 'mark_deprecated' ] = operation == 'mark as deprecated'
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='deprecate',
                                                                  **kwd ) )
        if 'message' not in kwd:
            message = 'This list contains repositories that match the following criteria:<br>'
            message += '<ul>'
            message += '<li>the latest installable revision has <b>Skip automated testing of tools in this '
            message += 'revision</b> checked if the repository type is <b>Unrestricted</b> or <b>Skip '
            message += 'automated testing of this tool dependency recipe</b> checked if the repository '
            message += 'type is <b>Tool dependency definition</b></li>'
            message += '</ul>'
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'warning'
        return self.repositories_with_skip_tests_checked_grid( trans, **kwd )

    @web.expose
    def browse_repository( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        commit_message = escape( kwd.get( 'commit_message', 'Deleted selected files' ) )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        # Update repository files for browsing.
        hg_util.update_repository( repo )
        changeset_revision = repository.tip( trans.app )
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              id,
                                                                                              changeset_revision,
                                                                                              metadata_only=True )
        repository_type_select_field = rt_util.build_repository_type_select_field( trans, repository=repository )
        return trans.fill_template( '/webapps/tool_shed/repository/browse_repository.mako',
                                    repository=repository,
                                    changeset_revision=changeset_revision,
                                    metadata=metadata,
                                    commit_message=commit_message,
                                    repository_type_select_field=repository_type_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    def browse_repository_dependencies( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            # The received id is a RepositoryMetadata id.
            repository_metadata_id = kwd[ 'id' ]
            repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, repository_metadata_id )
            repository_id = trans.security.encode_id( repository_metadata.repository_id )
            changeset_revision = repository_metadata.changeset_revision
            new_kwd = dict( id=repository_id,
                            changeset_revision=changeset_revision )
            if operation == "browse_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_repository',
                                                                  **new_kwd ) )
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **new_kwd ) )
        return self.repository_dependencies_grid( trans, **kwd )

    @web.expose
    def browse_tools( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            # The received id is a RepositoryMetadata id.
            repository_metadata_id = kwd['id' ]
            repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, repository_metadata_id )
            repository_id = trans.security.encode_id( repository_metadata.repository_id )
            changeset_revision = repository_metadata.changeset_revision
            new_kwd = dict( id=repository_id,
                            changeset_revision=changeset_revision )
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **new_kwd ) )
        return self.tools_grid( trans, **kwd )

    @web.expose
    def browse_tool_dependencies( self, trans, **kwd ):
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            # The received id is a RepositoryMetadata id.
            repository_metadata_id = kwd[ 'id' ]
            repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, repository_metadata_id )
            repository_id = trans.security.encode_id( repository_metadata.repository_id )
            changeset_revision = repository_metadata.changeset_revision
            new_kwd = dict( id=repository_id,
                            changeset_revision=changeset_revision )
            if operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **new_kwd ) )
        return self.tool_dependencies_grid( trans, **kwd )

    @web.expose
    def browse_valid_categories( self, trans, **kwd ):
        """Filter repositories per category by those that are valid for installing into Galaxy."""
        # The request came from Galaxy, so restrict category links to display only valid repository changeset revisions.
        galaxy_url = common_util.handle_galaxy_url( trans, **kwd )
        if galaxy_url:
            kwd[ 'galaxy_url' ] = galaxy_url
        if 'f-free-text-search' in kwd:
            if kwd[ 'f-free-text-search' ] == 'All':
                # The user performed a search, then clicked the "x" to eliminate the search criteria.
                new_kwd = {}
                return self.valid_category_grid( trans, **new_kwd )
            # Since we are searching valid repositories and not categories, redirect to browse_valid_repositories().
            if 'id' in kwd and 'f-free-text-search' in kwd and kwd[ 'id' ] == kwd[ 'f-free-text-search' ]:
                # The value of 'id' has been set to the search string, which is a repository name.
                # We'll try to get the desired encoded repository id to pass on.
                try:
                    name = kwd[ 'id' ]
                    repository = suc.get_repository_by_name( trans.app, name )
                    kwd[ 'id' ] = trans.security.encode_id( repository.id )
                except:
                    pass
            return self.browse_valid_repositories( trans, **kwd )
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation in [ "valid_repositories_by_category", "valid_repositories_by_user" ]:
                # Eliminate the current filters if any exist.
                for k, v in kwd.items():
                    if k.startswith( 'f-' ):
                        del kwd[ k ]
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='browse_valid_repositories',
                                                                  **kwd ) )
        title = trans.app.repository_grid_filter_manager.get_grid_title( trans,
                                                                         trailing_string='by Category',
                                                                         default='Categories of Valid Repositories' )
        self.valid_category_grid.title = title
        return self.valid_category_grid( trans, **kwd )

    @web.expose
    def browse_valid_repositories( self, trans, **kwd ):
        """Filter repositories to those that are installable into Galaxy."""
        galaxy_url = common_util.handle_galaxy_url( trans, **kwd )
        if galaxy_url:
            kwd[ 'galaxy_url' ] = galaxy_url
        repository_id = kwd.get( 'id', None )
        if 'f-free-text-search' in kwd:
            if 'f-Category.name' in kwd:
                # The user browsed to a category and then entered a search string, so get the category associated with its value.
                category_name = kwd[ 'f-Category.name' ]
                category = suc.get_category_by_name( trans.app, category_name )
                # Set the id value in kwd since it is required by the ValidRepositoryGrid.build_initial_query method.
                kwd[ 'id' ] = trans.security.encode_id( category.id )
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "preview_tools_in_changeset":
                repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
                repository_metadata = metadata_util.get_latest_repository_metadata( trans.app, repository.id, downloadable=True )
                latest_installable_changeset_revision = repository_metadata.changeset_revision
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='preview_tools_in_changeset',
                                                                  repository_id=repository_id,
                                                                  changeset_revision=latest_installable_changeset_revision ) )
            elif operation == "valid_repositories_by_category":
                # Eliminate the current filters if any exist.
                for k, v in kwd.items():
                    if k.startswith( 'f-' ):
                        del kwd[ k ]
                category_id = kwd.get( 'id', None )
                category = suc.get_category( trans.app, category_id )
                kwd[ 'f-Category.name' ] = category.name
        selected_changeset_revision, repository = suc.get_repository_from_refresh_on_change( trans.app, **kwd )
        if repository:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='preview_tools_in_changeset',
                                                              repository_id=trans.security.encode_id( repository.id ),
                                                              changeset_revision=selected_changeset_revision ) )
        url_args = dict( action='browse_valid_repositories',
                         operation='preview_tools_in_changeset',
                         repository_id=repository_id )
        self.valid_repository_grid.operations = [ grids.GridOperation( "Preview and install",
                                                                    url_args=url_args,
                                                                    allow_multiple=False,
                                                                    async_compatible=False ) ]
        title = trans.app.repository_grid_filter_manager.get_grid_title( trans,
                                                                         trailing_string='',
                                                                         default='Valid Repositories' )
        self.valid_repository_grid.title = title
        return self.valid_repository_grid( trans, **kwd )

    @web.expose
    def check_for_updates( self, trans, **kwd ):
        """Handle a request from a local Galaxy instance."""
        message = escape( kwd.get( 'message', '' ) )
        # If the request originated with the UpdateRepositoryManager, it will not include a galaxy_url.
        galaxy_url = common_util.handle_galaxy_url( trans, **kwd )
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        # Default to the current changeset revision.
        update_to_ctx = hg_util.get_changectx_for_changeset( repo, changeset_revision )
        latest_changeset_revision = changeset_revision
        from_update_manager = kwd.get( 'from_update_manager', False )
        if from_update_manager:
            update = 'true'
            no_update = 'false'
        elif galaxy_url:
            # Start building up the url to redirect back to the calling Galaxy instance.
            params = '?tool_shed_url=%s&name=%s&owner=%s&changeset_revision=%s&latest_changeset_revision=' % \
                ( web.url_for( '/', qualified=True ),
                  str( repository.name ),
                  str( repository.user.username ),
                  changeset_revision )
            url = common_util.url_join( galaxy_url,
                                        'admin_toolshed/update_to_changeset_revision%s' % params )
        else:
            message = 'Unable to check for updates due to an invalid Galaxy URL: <b>%s</b>.  ' % galaxy_url
            message += 'You may need to enable third-party cookies in your browser.  '
            return trans.show_error_message( message )
        if changeset_revision == repository.tip( trans.app ):
            # If changeset_revision is the repository tip, there are no additional updates.
            if from_update_manager:
                return no_update
            # Return the same value for changeset_revision and latest_changeset_revision.
            url += latest_changeset_revision
        else:
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                     trans.security.encode_id( repository.id ),
                                                                                     changeset_revision )
            if repository_metadata:
                # If changeset_revision is in the repository_metadata table for this repository, there are no
                # additional updates.
                if from_update_manager:
                    return no_update
                else:
                    # Return the same value for changeset_revision and latest_changeset_revision.
                    url += latest_changeset_revision
            else:
                # The changeset_revision column in the repository_metadata table has been updated with a new
                # changeset_revision value since the repository was installed.  We need to find the changeset_revision
                # to which we need to update.
                update_to_changeset_hash = None
                for changeset in repo.changelog:
                    changeset_hash = str( repo.changectx( changeset ) )
                    hg_util.get_changectx_for_changeset( repo, changeset_hash )
                    if update_to_changeset_hash:
                        if changeset_hash == repository.tip( trans.app ):
                            update_to_ctx = hg_util.get_changectx_for_changeset( repo, changeset_hash )
                            latest_changeset_revision = changeset_hash
                            break
                        else:
                            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                                     trans.security.encode_id( repository.id ),
                                                                                                     changeset_hash )
                            if repository_metadata:
                                # We found a RepositoryMetadata record.
                                update_to_ctx = hg_util.get_changectx_for_changeset( repo, changeset_hash )
                                latest_changeset_revision = changeset_hash
                                break
                            else:
                                update_to_changeset_hash = changeset_hash
                    else:
                        if changeset_hash == changeset_revision:
                            # We've found the changeset in the changelog for which we need to get the next update.
                            update_to_changeset_hash = changeset_hash
                if from_update_manager:
                    if latest_changeset_revision == changeset_revision:
                        return no_update
                    return update
                url += str( latest_changeset_revision )
        url += '&latest_ctx_rev=%s' % str( update_to_ctx.rev() )
        return trans.response.send_redirect( url )

    @web.expose
    def contact_owner( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              id,
                                                                                              repository.tip( trans.app ),
                                                                                              metadata_only=True )
        if trans.user and trans.user.email:
            return trans.fill_template( "/webapps/tool_shed/repository/contact_owner.mako",
                                        repository=repository,
                                        metadata=metadata,
                                        message=message,
                                        status=status )
        else:
            # Do all we can to eliminate spam.
            return trans.show_error_message( "You must be logged in to contact the owner of a repository." )

    @web.expose
    def create_galaxy_docker_image( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository_ids = util.listify( kwd.get( 'id', '' ) )
        if 'operation' in kwd:
            if repository_ids:
                operation = kwd[ 'operation' ].lower()
                if operation == "include in docker image":
                    repository_tups = []
                    for repository_id in repository_ids:
                        repository = suc.get_repository_by_id( trans.app, repository_id )
                        repository_tups.append( ( str( repository.name ),
                                                  str( repository.user.username ),
                                                  str( repository.type ) ) )
                    return trans.fill_template( "/webapps/tool_shed/repository/docker_image_repositories.mako",
                                                id=','.join( repository_ids ),
                                                repository_tups=repository_tups,
                                                message=message,
                                                status=status )
            else:
                # This can only occur when there is a multi-select grid with check boxes and an operation,
                # and the user clicked the operation button without checking any of the check boxes.
                kwd[ 'message' ] = "No items were selected."
                kwd[ 'status' ] = 'error'
        elif kwd.get( 'create_docker_image_button', False ):
            tmp_image_dir = tempfile.mkdtemp( prefix="tmp-toolshed-cdidir" )
            docker_file_name = 'Dockerfile'
            docker_file_path = os.path.join( tmp_image_dir, docker_file_name )
            tool_shed_url = tool_shed_url = web.url_for( '/', qualified=True )
            repository_string = ''
            for repository_id in repository_ids:
                repository = suc.get_repository_by_id( trans.app, repository_id )
                template = basic_util.SELECTED_REPOSITORIES_TEMPLATE
                repository_template = \
                    string.Template( template ).safe_substitute( tool_shed_url=tool_shed_url,
                                                                 repository_owner=str( repository.user.username ) ,
                                                                 repository_name=str( repository.name ) )
                repository_string = '%s\n%s' % ( repository_string, repository_template )
            template = basic_util.DOCKER_IMAGE_TEMPLATE
            docker_image_template = \
                string.Template( template ).safe_substitute( selected_repositories=repository_string )
            docker_image_string = docker_image_template
            trans.response.set_content_type( 'application/text/plain' )
            trans.response.headers[ "Content-Disposition" ] = 'attachment; filename="%s"' % docker_file_name
            opened_file = open( docker_file_path, "w" )
            opened_file.write( docker_image_string )
            opened_file.close()
            opened_file = open( docker_file_path, "r" )
            # Make sure the file is removed from disk after the contents have been downloaded.
            os.unlink( docker_file_path )
            docker_file_path, docker_file_name = os.path.split( docker_file_path )
            basic_util.remove_dir( docker_file_path )
            return opened_file
        return self.docker_image_grid( trans, **kwd )

    @web.expose
    def create_repository( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        categories = suc.get_categories( trans )
        if not categories:
            message = 'No categories have been configured in this instance of the Galaxy Tool Shed.  '
            message += 'An administrator needs to create some via the Administrator control panel before creating repositories.'
            status = 'error'
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              message=message,
                                                              status=status ) )
        name = kwd.get( 'name', '' ).strip()
        remote_repository_url = kwd.get( 'remote_repository_url', '' )
        homepage_url = kwd.get( 'homepage_url', '' )
        description = kwd.get( 'description', '' )
        long_description = kwd.get( 'long_description', '' )
        category_ids = util.listify( kwd.get( 'category_id', '' ) )
        selected_categories = [ trans.security.decode_id( id ) for id in category_ids ]
        repository_type = kwd.get( 'repository_type', rt_util.UNRESTRICTED )
        if kwd.get( 'create_repository_button', False ):
            error = False
            message = repository_util.validate_repository_name( trans.app, name, trans.user )
            if message:
                error = True
            if not description:
                message = 'Enter a description.'
                error = True
            if error:
                status = 'error'
            else:
                repository, message = repository_util.create_repository( trans.app,
                                                                         name,
                                                                         repository_type,
                                                                         description,
                                                                         long_description,
                                                                         user_id=trans.user.id,
                                                                         category_ids=category_ids,
                                                                         remote_repository_url=remote_repository_url,
                                                                         homepage_url=homepage_url )
                trans.response.send_redirect( web.url_for( controller='repository',
                                                           action='manage_repository',
                                                           message=message,
                                                           id=trans.security.encode_id( repository.id ) ) )
        repository_type_select_field = rt_util.build_repository_type_select_field( trans )
        return trans.fill_template( '/webapps/tool_shed/repository/create_repository.mako',
                                    name=name,
                                    remote_repository_url=remote_repository_url,
                                    homepage_url=homepage_url,
                                    description=description,
                                    long_description=long_description,
                                    selected_categories=selected_categories,
                                    categories=categories,
                                    repository_type_select_field=repository_type_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    @web.require_login( "deprecate repository" )
    def deprecate( self, trans, **kwd ):
        """Mark a repository in the tool shed as deprecated or not deprecated."""
        # Marking a repository in the tool shed as deprecated has no effect on any downloadable changeset
        # revisions that may be associated with the repository.  Revisions are not marked as not downlaodable
        # because those that have installed the repository must be allowed to get updates.
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository_id = kwd.get( 'id', None )
        repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
        mark_deprecated = util.string_as_bool( kwd.get( 'mark_deprecated', False ) )
        repository.deprecated = mark_deprecated
        trans.sa_session.add( repository )
        trans.sa_session.flush()
        if mark_deprecated:
            # Update the repository registry.
            trans.app.repository_registry.remove_entry( repository )
            message = 'The repository <b>%s</b> has been marked as deprecated.' % escape( repository.name )
        else:
            # Update the repository registry.
            trans.app.repository_registry.add_entry( repository )
            message = 'The repository <b>%s</b> has been marked as not deprecated.' % escape( repository.name )
        trans.response.send_redirect( web.url_for( controller='repository',
                                                   action='browse_repositories',
                                                   operation='repositories_i_own',
                                                   message=message,
                                                   status=status ) )

    @web.expose
    def display_image_in_repository( self, trans, **kwd ):
        """
        Open an image file that is contained in repository or that is referenced by a URL for display.  The image can be defined in
        either a README.rst file contained in the repository or the help section of a Galaxy tool config that is contained in the repository.
        The following image definitions are all supported.  The former $PATH_TO_IMAGES is no longer required, and is now ignored.
        .. image:: https://raw.github.com/galaxy/some_image.png
        .. image:: $PATH_TO_IMAGES/some_image.png
        .. image:: /static/images/some_image.gif
        .. image:: some_image.jpg
        .. image:: /deep/some_image.png
        """
        repository_id = kwd.get( 'repository_id', None )
        relative_path_to_image_file = kwd.get( 'image_file', None )
        if repository_id and relative_path_to_image_file:
            repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
            if repository:
                repo_files_dir = repository.repo_path( trans.app )
                path_to_file = suc.get_absolute_path_to_file_in_repository( repo_files_dir, relative_path_to_image_file )
                if os.path.exists( path_to_file ):
                    file_name = os.path.basename( relative_path_to_image_file )
                    try:
                        extension = file_name.split( '.' )[ -1 ]
                    except Exception:
                        extension = None
                    if extension:
                        mimetype = trans.app.datatypes_registry.get_mimetype_by_extension( extension )
                        if mimetype:
                            trans.response.set_content_type( mimetype )
                    return open( path_to_file, 'r' )
        return None

    @web.expose
    def display_tool( self, trans, repository_id, tool_config, changeset_revision, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        render_repository_actions_for = kwd.get( 'render_repository_actions_for', 'tool_shed' )
        tv = tool_validator.ToolValidator( trans.app )
        repository, tool, message = tv.load_tool_from_changeset_revision( repository_id,
                                                                          changeset_revision,
                                                                          tool_config )
        if message:
            status = 'error'
        tool_state = tool_util.new_state( trans, tool, invalid=False )
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              repository_id,
                                                                                              changeset_revision,
                                                                                              metadata_only=True )
        try:
            return trans.fill_template( "/webapps/tool_shed/repository/tool_form.mako",
                                        repository=repository,
                                        render_repository_actions_for=render_repository_actions_for,
                                        metadata=metadata,
                                        changeset_revision=changeset_revision,
                                        tool=tool,
                                        tool_state=tool_state,
                                        message=message,
                                        status=status )
        except Exception, e:
            message = "Error displaying tool, probably due to a problem in the tool config.  The exception is: %s." % str( e )
        if trans.webapp.name == 'galaxy' or render_repository_actions_for == 'galaxy':
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='preview_tools_in_changeset',
                                                              repository_id=repository_id,
                                                              changeset_revision=changeset_revision,
                                                              message=message,
                                                              status='error' ) )
        return trans.response.send_redirect( web.url_for( controller='repository',
                                                          action='browse_repositories',
                                                          operation='view_or_manage_repository',
                                                          id=repository_id,
                                                          changeset_revision=changeset_revision,
                                                          message=message,
                                                          status='error' ) )

    @web.expose
    def download( self, trans, repository_id, changeset_revision, file_type, **kwd ):
        """Download an archive of the repository files compressed as zip, gz or bz2."""
        # FIXME: thgis will currently only download the repository tip, no matter which installable changeset_revision is being viewed.
        # This should be enhanced to use the export method below, which accounts for the currently viewed changeset_revision.
        repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
        # Allow hgweb to handle the download.  This requires the tool shed
        # server account's .hgrc file to include the following setting:
        # [web]
        # allow_archive = bz2, gz, zip
        file_type_str = basic_util.get_file_type_str( changeset_revision, file_type )
        repository.times_downloaded += 1
        trans.sa_session.add( repository )
        trans.sa_session.flush()
        tool_shed_url = web.url_for( '/', qualified=True )
        download_url = common_util.url_join( tool_shed_url,
                                             'repos',
                                             str( repository.user.username ),
                                             str( repository.name ),
                                             'archive',
                                             file_type_str )
        return trans.response.send_redirect( download_url )

    @web.expose
    def export( self, trans, repository_id, changeset_revision, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        export_repository_dependencies = kwd.get( 'export_repository_dependencies', '' )
        repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
        if kwd.get( 'export_repository_button', False ):
            # We'll currently support only gzip-compressed tar archives.
            export_repository_dependencies = CheckboxField.is_checked( export_repository_dependencies )
            tool_shed_url = web.url_for( '/', qualified=True )
            erm = capsule_manager.ExportRepositoryManager( app=trans.app,
                                                           user=trans.user,
                                                           tool_shed_url=tool_shed_url,
                                                           repository=repository,
                                                           changeset_revision=changeset_revision,
                                                           export_repository_dependencies=export_repository_dependencies,
                                                           using_api=False )
            repositories_archive, error_message = erm.export_repository()
            repositories_archive_filename = os.path.basename( repositories_archive.name )
            if error_message:
                message = error_message
                status = 'error'
            else:
                trans.response.set_content_type( 'application/x-gzip' )
                trans.response.headers[ "Content-Disposition" ] = 'attachment; filename="%s"' % ( repositories_archive_filename )
                opened_archive = open( repositories_archive.name )
                # Make sure the file is removed from disk after the contents have been downloaded.
                os.unlink( repositories_archive.name )
                repositories_archive_path, file_name = os.path.split( repositories_archive.name )
                basic_util.remove_dir( repositories_archive_path )
                return opened_archive
        repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, repository_id, changeset_revision )
        metadata = repository_metadata.metadata
        toolshed_base_url = str( web.url_for( '/', qualified=True ) ).rstrip( '/' )
        # Initialize the repository dependency RelationBuilder.
        rb = relation_builder.RelationBuilder( trans.app, repository, repository_metadata, toolshed_base_url )
        # Work-around to ensure repositories that contain packages needed only for compiling
        # a dependent package are included in the capsule.
        rb.set_filter_dependencies_needed_for_compiling( False )
        # Get a dictionary of all repositories upon which the contents of the current repository_metadata record depend.
        repository_dependencies = rb.get_repository_dependencies_for_changeset_revision()
        if repository_dependencies:
            # Only display repository dependencies if they exist.
            exclude = [ 'datatypes', 'invalid_repository_dependencies', 'invalid_tool_dependencies', 'invalid_tools',
                        'readme_files', 'tool_dependencies', 'tools', 'tool_test_results', 'workflows', 'data_manager' ]
            tsucm = ToolShedUtilityContainerManager( trans.app )
            containers_dict = tsucm.build_repository_containers( repository,
                                                                 changeset_revision,
                                                                 repository_dependencies,
                                                                 repository_metadata,
                                                                 exclude=exclude )
            export_repository_dependencies_check_box = CheckboxField( 'export_repository_dependencies', checked=True )
        else:
            containers_dict = None
            export_repository_dependencies_check_box = None
        revision_label = hg_util.get_revision_label( trans.app, repository, changeset_revision, include_date=True )
        return trans.fill_template( "/webapps/tool_shed/repository/export_repository.mako",
                                    changeset_revision=changeset_revision,
                                    containers_dict=containers_dict,
                                    export_repository_dependencies_check_box=export_repository_dependencies_check_box,
                                    repository=repository,
                                    repository_metadata=repository_metadata,
                                    revision_label=revision_label,
                                    metadata=metadata,
                                    message=message,
                                    status=status )

    @web.expose
    def export_via_api( self, trans, **kwd ):
        """Return an exported gzip compressed repository archive file opened for reading."""
        encoded_repositories_archive_name = kwd.get( 'encoded_repositories_archive_name', None )
        if encoded_repositories_archive_name:
            repositories_archive_name = encoding_util.tool_shed_decode( encoded_repositories_archive_name )
            opened_archive = open( repositories_archive_name )
            # Make sure the file is removed from disk after the contents have been downloaded.
            os.unlink( repositories_archive_name )
            return opened_archive
        return ''

    @web.expose
    def find_tools( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        common_util.handle_galaxy_url( trans, **kwd )
        if 'operation' in kwd:
            item_id = kwd.get( 'id', '' )
            if item_id:
                operation = kwd[ 'operation' ].lower()
                is_admin = trans.user_is_admin()
                if operation == "view_or_manage_repository":
                    # The received id is a RepositoryMetadata id, so we have to get the repository id.
                    repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, item_id )
                    repository_id = trans.security.encode_id( repository_metadata.repository.id )
                    repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
                    kwd[ 'id' ] = repository_id
                    kwd[ 'changeset_revision' ] = repository_metadata.changeset_revision
                    if trans.webapp.name == 'tool_shed' and ( is_admin or repository.user == trans.user ):
                        a = 'manage_repository'
                    else:
                        a = 'view_repository'
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action=a,
                                                                      **kwd ) )
                if operation == "install to galaxy":
                    # We've received a list of RepositoryMetadata ids, so we need to build a list of associated Repository ids.
                    encoded_repository_ids = []
                    changeset_revisions = []
                    for repository_metadata_id in util.listify( item_id ):
                        repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, repository_metadata_id )
                        encoded_repository_ids.append( trans.security.encode_id( repository_metadata.repository.id ) )
                        changeset_revisions.append( repository_metadata.changeset_revision )
                    new_kwd = {}
                    new_kwd[ 'repository_ids' ] = encoded_repository_ids
                    new_kwd[ 'changeset_revisions' ] = changeset_revisions
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action='install_repositories_by_revision',
                                                                      **new_kwd ) )
            else:
                # This can only occur when there is a multi-select grid with check boxes and an operation,
                # and the user clicked the operation button without checking any of the check boxes.
                return trans.show_error_message( "No items were selected." )
        tool_ids = [ item.lower() for item in util.listify( kwd.get( 'tool_id', '' ) ) ]
        tool_names = [ item.lower() for item in util.listify( kwd.get( 'tool_name', '' ) ) ]
        tool_versions = [ item.lower() for item in util.listify( kwd.get( 'tool_version', '' ) ) ]
        exact_matches = kwd.get( 'exact_matches', '' )
        exact_matches_checked = CheckboxField.is_checked( exact_matches )
        match_tuples = []
        ok = True
        if tool_ids or tool_names or tool_versions:
            ok, match_tuples = search_util.search_repository_metadata( trans.app,
                                                                       exact_matches_checked,
                                                                       tool_ids=tool_ids,
                                                                       tool_names=tool_names,
                                                                       tool_versions=tool_versions )
            if ok:
                kwd[ 'match_tuples' ] = match_tuples
                # Render the list view
                if trans.webapp.name == 'galaxy':
                    # Our initial request originated from a Galaxy instance.
                    global_actions = [ grids.GridAction( "Browse valid repositories",
                                                         dict( controller='repository', action='browse_valid_categories' ) ),
                                       grids.GridAction( "Search for valid tools",
                                                         dict( controller='repository', action='find_tools' ) ),
                                       grids.GridAction( "Search for workflows",
                                                         dict( controller='repository', action='find_workflows' ) ) ]
                    self.install_matched_repository_grid.global_actions = global_actions
                    install_url_args = dict( controller='repository', action='find_tools' )
                    operations = [ grids.GridOperation( "Install", url_args=install_url_args, allow_multiple=True, async_compatible=False ) ]
                    self.install_matched_repository_grid.operations = operations
                    return self.install_matched_repository_grid( trans, **kwd )
                else:
                    kwd[ 'message' ] = "tool id: <b>%s</b><br/>tool name: <b>%s</b><br/>tool version: <b>%s</b><br/>exact matches only: <b>%s</b>" % \
                        ( basic_util.stringify( tool_ids ),
                          escape( basic_util.stringify( tool_names ) ),
                          escape( basic_util.stringify( tool_versions ) ),
                          str( exact_matches_checked ) )
                    self.matched_repository_grid.title = "Repositories with matching tools"
                    return self.matched_repository_grid( trans, **kwd )
            else:
                message = "No search performed - each field must contain the same number of comma-separated items."
                status = "error"
        exact_matches_check_box = CheckboxField( 'exact_matches', checked=exact_matches_checked )
        return trans.fill_template( '/webapps/tool_shed/repository/find_tools.mako',
                                    tool_id=basic_util.stringify( tool_ids ),
                                    tool_name=basic_util.stringify( tool_names ),
                                    tool_version=basic_util.stringify( tool_versions ),
                                    exact_matches_check_box=exact_matches_check_box,
                                    message=message,
                                    status=status )

    @web.expose
    def find_workflows( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        common_util.handle_galaxy_url( trans, **kwd )
        if 'operation' in kwd:
            item_id = kwd.get( 'id', '' )
            if item_id:
                operation = kwd[ 'operation' ].lower()
                is_admin = trans.user_is_admin()
                if operation == "view_or_manage_repository":
                    # The received id is a RepositoryMetadata id, so we have to get the repository id.
                    repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, item_id )
                    repository_id = trans.security.encode_id( repository_metadata.repository.id )
                    repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
                    kwd[ 'id' ] = repository_id
                    kwd[ 'changeset_revision' ] = repository_metadata.changeset_revision
                    if trans.webapp.name == 'tool_shed' and ( is_admin or repository.user == trans.user ):
                        a = 'manage_repository'
                    else:
                        a = 'view_repository'
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action=a,
                                                                      **kwd ) )
                if operation == "install to galaxy":
                    # We've received a list of RepositoryMetadata ids, so we need to build a list of associated Repository ids.
                    encoded_repository_ids = []
                    changeset_revisions = []
                    for repository_metadata_id in util.listify( item_id ):
                        repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, item_id )
                        encoded_repository_ids.append( trans.security.encode_id( repository_metadata.repository.id ) )
                        changeset_revisions.append( repository_metadata.changeset_revision )
                    new_kwd = {}
                    new_kwd[ 'repository_ids' ] = encoded_repository_ids
                    new_kwd[ 'changeset_revisions' ] = changeset_revisions
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action='install_repositories_by_revision',
                                                                      **new_kwd ) )
            else:
                # This can only occur when there is a multi-select grid with check boxes and an operation,
                # and the user clicked the operation button without checking any of the check boxes.
                return trans.show_error_message( "No items were selected." )
        if 'find_workflows_button' in kwd:
            workflow_names = [ item.lower() for item in util.listify( kwd.get( 'workflow_name', '' ) ) ]
            exact_matches = kwd.get( 'exact_matches', '' )
            exact_matches_checked = CheckboxField.is_checked( exact_matches )
            match_tuples = []
            ok = True
            if workflow_names:
                ok, match_tuples = search_util.search_repository_metadata( trans.app,
                                                                           exact_matches_checked,
                                                                           workflow_names=workflow_names )
            else:
                ok, match_tuples = search_util.search_repository_metadata( trans.app,
                                                                           exact_matches_checked,
                                                                           workflow_names=[],
                                                                           all_workflows=True )
            if ok:
                kwd[ 'match_tuples' ] = match_tuples
                if trans.webapp.name == 'galaxy':
                    # Our initial request originated from a Galaxy instance.
                    global_actions = [ grids.GridAction( "Browse valid repositories",
                                                         dict( controller='repository', action='browse_valid_repositories' ) ),
                                       grids.GridAction( "Search for valid tools",
                                                         dict( controller='repository', action='find_tools' ) ),
                                       grids.GridAction( "Search for workflows",
                                                         dict( controller='repository', action='find_workflows' ) ) ]
                    self.install_matched_repository_grid.global_actions = global_actions
                    install_url_args = dict( controller='repository', action='find_workflows' )
                    operations = [ grids.GridOperation( "Install", url_args=install_url_args, allow_multiple=True, async_compatible=False ) ]
                    self.install_matched_repository_grid.operations = operations
                    return self.install_matched_repository_grid( trans, **kwd )
                else:
                    kwd[ 'message' ] = "workflow name: <b>%s</b><br/>exact matches only: <b>%s</b>" % \
                        ( escape( basic_util.stringify( workflow_names ) ), str( exact_matches_checked ) )
                    self.matched_repository_grid.title = "Repositories with matching workflows"
                    return self.matched_repository_grid( trans, **kwd )
            else:
                message = "No search performed - each field must contain the same number of comma-separated items."
                status = "error"
        else:
            exact_matches_checked = False
            workflow_names = []
        exact_matches_check_box = CheckboxField( 'exact_matches', checked=exact_matches_checked )
        return trans.fill_template( '/webapps/tool_shed/repository/find_workflows.mako',
                                    workflow_name=basic_util.stringify( workflow_names ),
                                    exact_matches_check_box=exact_matches_check_box,
                                    message=message,
                                    status=status )

    @web.expose
    def generate_workflow_image( self, trans, workflow_name, repository_metadata_id=None ):
        """Return an svg image representation of a workflow dictionary created when the workflow was exported."""
        return workflow_util.generate_workflow_image( trans, workflow_name, repository_metadata_id=repository_metadata_id, repository_id=None )

    @web.expose
    def get_changeset_revision_and_ctx_rev( self, trans, **kwd ):
        """Handle a request from a local Galaxy instance to retrieve the changeset revision hash to which an installed repository can be updated."""
        def has_galaxy_utilities( repository_metadata ):
            has_galaxy_utilities_dict = dict( includes_data_managers=False,
                                              includes_datatypes=False,
                                              includes_tools=False,
                                              includes_tools_for_display_in_tool_panel=False,
                                              has_repository_dependencies=False,
                                              has_repository_dependencies_only_if_compiling_contained_td=False,
                                              includes_tool_dependencies=False,
                                              includes_workflows=False )
            if repository_metadata:
                metadata = repository_metadata.metadata
                if metadata:
                    if 'data_manager' in metadata:
                        has_galaxy_utilities_dict[ 'includes_data_managers' ] = True
                    if 'datatypes' in metadata:
                        has_galaxy_utilities_dict[ 'includes_datatypes' ] = True
                    if 'tools' in metadata:
                        has_galaxy_utilities_dict[ 'includes_tools' ] = True
                    if 'tool_dependencies' in metadata:
                        has_galaxy_utilities_dict[ 'includes_tool_dependencies' ] = True
                    repository_dependencies_dict = metadata.get( 'repository_dependencies', {} )
                    repository_dependencies = repository_dependencies_dict.get( 'repository_dependencies', [] )
                    has_repository_dependencies, has_repository_dependencies_only_if_compiling_contained_td = \
                        suc.get_repository_dependency_types( repository_dependencies )
                    has_galaxy_utilities_dict[ 'has_repository_dependencies' ] = has_repository_dependencies
                    has_galaxy_utilities_dict[ 'has_repository_dependencies_only_if_compiling_contained_td' ] = \
                        has_repository_dependencies_only_if_compiling_contained_td
                    if 'workflows' in metadata:
                        has_galaxy_utilities_dict[ 'includes_workflows' ] = True
            return has_galaxy_utilities_dict
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                 trans.security.encode_id( repository.id ),
                                                                                 changeset_revision )
        has_galaxy_utilities_dict = has_galaxy_utilities( repository_metadata )
        includes_data_managers = has_galaxy_utilities_dict[ 'includes_data_managers' ]
        includes_datatypes = has_galaxy_utilities_dict[ 'includes_datatypes' ]
        includes_tools = has_galaxy_utilities_dict[ 'includes_tools' ]
        includes_tools_for_display_in_tool_panel = has_galaxy_utilities_dict[ 'includes_tools_for_display_in_tool_panel' ]
        includes_tool_dependencies = has_galaxy_utilities_dict[ 'includes_tool_dependencies' ]
        has_repository_dependencies = has_galaxy_utilities_dict[ 'has_repository_dependencies' ]
        has_repository_dependencies_only_if_compiling_contained_td = \
            has_galaxy_utilities_dict[ 'has_repository_dependencies_only_if_compiling_contained_td' ]
        includes_workflows = has_galaxy_utilities_dict[ 'includes_workflows' ]
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        # Default to the received changeset revision and ctx_rev.
        update_to_ctx = hg_util.get_changectx_for_changeset( repo, changeset_revision )
        ctx_rev = str( update_to_ctx.rev() )
        latest_changeset_revision = changeset_revision
        update_dict = dict( changeset_revision=changeset_revision,
                            ctx_rev=ctx_rev,
                            includes_data_managers=includes_data_managers,
                            includes_datatypes=includes_datatypes,
                            includes_tools=includes_tools,
                            includes_tools_for_display_in_tool_panel=includes_tools_for_display_in_tool_panel,
                            includes_tool_dependencies=includes_tool_dependencies,
                            has_repository_dependencies=has_repository_dependencies,
                            has_repository_dependencies_only_if_compiling_contained_td=has_repository_dependencies_only_if_compiling_contained_td,
                            includes_workflows=includes_workflows )
        if changeset_revision == repository.tip( trans.app ):
            # If changeset_revision is the repository tip, there are no additional updates.
            return encoding_util.tool_shed_encode( update_dict )
        else:
            if repository_metadata:
                # If changeset_revision is in the repository_metadata table for this repository, there are no additional updates.
                return encoding_util.tool_shed_encode( update_dict )
            else:
                # The changeset_revision column in the repository_metadata table has been updated with a new changeset_revision value since the
                # repository was installed.  We need to find the changeset_revision to which we need to update.
                update_to_changeset_hash = None
                for changeset in repo.changelog:
                    includes_tools = False
                    has_repository_dependencies = False
                    has_repository_dependencies_only_if_compiling_contained_td = False
                    changeset_hash = str( repo.changectx( changeset ) )
                    hg_util.get_changectx_for_changeset( repo, changeset_hash )
                    if update_to_changeset_hash:
                        update_to_repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                                           trans.security.encode_id( repository.id ),
                                                                                                           changeset_hash )
                        if update_to_repository_metadata:
                            has_galaxy_utilities_dict = has_galaxy_utilities( repository_metadata )
                            includes_data_managers = has_galaxy_utilities_dict[ 'includes_data_managers' ]
                            includes_datatypes = has_galaxy_utilities_dict[ 'includes_datatypes' ]
                            includes_tools = has_galaxy_utilities_dict[ 'includes_tools' ]
                            includes_tools_for_display_in_tool_panel = has_galaxy_utilities_dict[ 'includes_tools_for_display_in_tool_panel' ]
                            includes_tool_dependencies = has_galaxy_utilities_dict[ 'includes_tool_dependencies' ]
                            has_repository_dependencies = has_galaxy_utilities_dict[ 'has_repository_dependencies' ]
                            has_repository_dependencies_only_if_compiling_contained_td = has_galaxy_utilities_dict[ 'has_repository_dependencies_only_if_compiling_contained_td' ]
                            includes_workflows = has_galaxy_utilities_dict[ 'includes_workflows' ]
                            # We found a RepositoryMetadata record.
                            if changeset_hash == repository.tip( trans.app ):
                                # The current ctx is the repository tip, so use it.
                                update_to_ctx = hg_util.get_changectx_for_changeset( repo, changeset_hash )
                                latest_changeset_revision = changeset_hash
                            else:
                                update_to_ctx = hg_util.get_changectx_for_changeset( repo, update_to_changeset_hash )
                                latest_changeset_revision = update_to_changeset_hash
                            break
                    elif not update_to_changeset_hash and changeset_hash == changeset_revision:
                        # We've found the changeset in the changelog for which we need to get the next update.
                        update_to_changeset_hash = changeset_hash
                update_dict[ 'includes_data_managers' ] = includes_data_managers
                update_dict[ 'includes_datatypes' ] = includes_datatypes
                update_dict[ 'includes_tools' ] = includes_tools
                update_dict[ 'includes_tools_for_display_in_tool_panel' ] = includes_tools_for_display_in_tool_panel
                update_dict[ 'includes_tool_dependencies' ] = includes_tool_dependencies
                update_dict[ 'includes_workflows' ] = includes_workflows
                update_dict[ 'has_repository_dependencies' ] = has_repository_dependencies
                update_dict[ 'has_repository_dependencies_only_if_compiling_contained_td' ] = has_repository_dependencies_only_if_compiling_contained_td
                update_dict[ 'changeset_revision' ] = str( latest_changeset_revision )
        update_dict[ 'ctx_rev' ] = str( update_to_ctx.rev() )
        return encoding_util.tool_shed_encode( update_dict )

    @web.expose
    def get_ctx_rev( self, trans, **kwd ):
        """Given a repository and changeset_revision, return the correct ctx.rev() value."""
        repository_name = kwd[ 'name' ]
        repository_owner = kwd[ 'owner' ]
        changeset_revision = kwd[ 'changeset_revision' ]
        repository = suc.get_repository_by_name_and_owner( trans.app, repository_name, repository_owner )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        ctx = hg_util.get_changectx_for_changeset( repo, changeset_revision )
        if ctx:
            return str( ctx.rev() )
        return ''

    @web.json
    def get_file_contents( self, trans, file_path ):
        # Avoid caching
        trans.response.headers['Pragma'] = 'no-cache'
        trans.response.headers['Expires'] = '0'
        return suc.get_repository_file_contents( file_path )

    @web.expose
    def get_functional_test_rss( self, trans, **kwd ):
        '''Return an RSS feed of the functional test results for the provided user, optionally filtered by the 'status' parameter.'''
        owner = kwd.get( 'owner', None )
        status = kwd.get( 'status', 'all' )
        if owner:
            user = suc.get_user_by_username( trans.app, owner )
        else:
            trans.response.status = 404
            return 'Missing owner parameter.'
        if user is None:
            trans.response.status = 404
            return 'No user found with username %s.' % owner
        if status == 'passed':
            # Return only metadata revisions where tools_functionally_correct is set to True.
            metadata_filter = and_( trans.model.RepositoryMetadata.table.c.includes_tools == True,
                                    trans.model.RepositoryMetadata.table.c.tools_functionally_correct == True,
                                    trans.model.RepositoryMetadata.table.c.time_last_tested is not None )  # noqa
        elif status == 'failed':
            # Return only metadata revisions where tools_functionally_correct is set to False.
            metadata_filter = and_( trans.model.RepositoryMetadata.table.c.includes_tools == True,
                                    trans.model.RepositoryMetadata.table.c.tools_functionally_correct == False,
                                    trans.model.RepositoryMetadata.table.c.time_last_tested is not None )  # noqa
        else:
            # Return all metadata entries for this user's repositories.
            metadata_filter = and_( trans.model.RepositoryMetadata.table.c.includes_tools == True,
                                    trans.model.RepositoryMetadata.table.c.time_last_tested is not None )

        tool_shed_url = web.url_for( '/', qualified=True )
        functional_test_results = []
        for repository_metadata in trans.sa_session.query( trans.model.RepositoryMetadata ) \
                                            .filter( metadata_filter ) \
                                            .join( trans.model.Repository ) \
                                            .filter( and_( trans.model.Repository.table.c.deleted == False,
                                                           trans.model.Repository.table.c.private == False,
                                                           trans.model.Repository.table.c.deprecated == False,
                                                           trans.model.Repository.table.c.user_id == user.id ) ):
            repository = repository_metadata.repository
            repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
            latest_downloadable_changeset_revsion = suc.get_latest_downloadable_changeset_revision( trans.app, repository, repo )
            if repository_metadata.changeset_revision == latest_downloadable_changeset_revsion:
                # We'll display only the test run for the latest installable revision in the rss feed.
                tool_test_results = repository_metadata.tool_test_results
                if tool_test_results is not None:
                    # The tool_test_results column used to contain a single dictionary, but was recently enhanced to contain
                    # a list of dictionaries, one for each install and test run.  We'll display only the latest run in the rss
                    # feed for nwo.
                    if isinstance( tool_test_results, list ):
                        tool_test_results = tool_test_results[ 0 ]
                    current_repository_errors = []
                    tool_dependency_errors = []
                    repository_dependency_errors = []
                    description_lines = []
                    # Per the RSS 2.0 specification, all dates in RSS feeds must be formatted as specified in RFC 822
                    # section 5.1, e.g. Sat, 07 Sep 2002 00:00:01 UT
                    if repository_metadata.time_last_tested is None:
                      time_tested = 'Thu, 01 Jan 1970 00:00:00 UT'
                    else:
                      time_tested = repository_metadata.time_last_tested.strftime( '%a, %d %b %Y %H:%M:%S UT' )
                    # Generate a citable URL for this repository with owner and changeset revision.
                    repository_citable_url = common_util.url_join( tool_shed_url,
                                                                   'view',
                                                                   str( user.username ),
                                                                   str( repository.name ),
                                                                   str( repository_metadata.changeset_revision ) )
                    passed_tests = len( tool_test_results.get( 'passed_tests', [] ) )
                    failed_tests = len( tool_test_results.get( 'failed_tests', [] ) )
                    missing_test_components = len( tool_test_results.get( 'missing_test_components', [] ) )
                    installation_errors = tool_test_results.get( 'installation_errors', [] )
                    if installation_errors:
                        tool_dependency_errors = installation_errors.get( 'tool_dependencies', [] )
                        repository_dependency_errors = installation_errors.get( 'repository_dependencies', [] )
                        current_repository_errors = installation_errors.get( 'current_repository', [] )
                    description_lines.append( '%d tests passed, %d tests failed, %d tests missing test components.' % \
                        ( passed_tests, failed_tests, missing_test_components ) )
                    if current_repository_errors:
                        description_lines.append( '\nThis repository did not install correctly. ' )
                    if tool_dependency_errors or repository_dependency_errors:
                        description_lines.append( '\n%d tool dependencies and %d repository dependencies failed to install. ' % \
                            ( len( tool_dependency_errors ), len( repository_dependency_errors ) ) )
                    title = 'Revision %s of %s' % ( repository_metadata.changeset_revision, repository.name )
                    # The guid attribute in an RSS feed's list of items allows a feed reader to choose not to show an item as updated
                    # if the guid is unchanged. For functional test results, the citable URL is sufficiently unique to enable
                    # that behavior.
                    functional_test_results.append( dict( title=title,
                                                          guid=repository_citable_url,
                                                          link=repository_citable_url,
                                                          description='\n'.join( description_lines ),
                                                          pubdate=time_tested ) )
        trans.response.set_content_type( 'application/rss+xml' )
        return trans.fill_template( '/rss.mako',
                                    title='Tool functional test results',
                                    link=tool_shed_url,
                                    description='Functional test results for repositories owned by %s.' % user.username,
                                    pubdate=strftime( '%a, %d %b %Y %H:%M:%S UT', gmtime() ),
                                    items=functional_test_results )

    @web.json
    def get_latest_downloadable_changeset_revision( self, trans, **kwd ):
        """
        Return the latest installable changeset revision for the repository associated with the received
        name and owner.  This method is called from Galaxy when attempting to install the latest revision
        of an installed repository.
        """
        repository_name = kwd.get( 'name', None )
        repository_owner = kwd.get( 'owner', None )
        if repository_name is not None and repository_owner is not None:
            repository = suc.get_repository_by_name_and_owner( trans.app, repository_name, repository_owner )
            if repository:
                repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
                return suc.get_latest_downloadable_changeset_revision( trans.app, repository, repo )
        return hg_util.INITIAL_CHANGELOG_HASH

    @web.json
    def get_readme_files( self, trans, **kwd ):
        """
        This method is called when installing or re-installing a single repository into a Galaxy instance.
        If the received changeset_revision includes one or more readme files, return them in a dictionary.
        """
        repository_name = kwd.get( 'name', None )
        repository_owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        if repository_name is not None and repository_owner is not None and changeset_revision is not None:
            repository = suc.get_repository_by_name_and_owner( trans.app, repository_name, repository_owner )
            if repository:
                repository_metadata = \
                    suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                       trans.security.encode_id( repository.id ),
                                                                       changeset_revision )
                if repository_metadata:
                    metadata = repository_metadata.metadata
                    if metadata:
                        return readme_util.build_readme_files_dict( trans.app,
                                                                    repository,
                                                                    changeset_revision,
                                                                    repository_metadata.metadata )
        return {}

    @web.json
    def get_repository_dependencies( self, trans, **kwd ):
        """
        Return an encoded dictionary of all repositories upon which the contents of the received repository
        depends.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        repository_id = trans.security.encode_id( repository.id )
        # We aren't concerned with repositories of type tool_dependency_definition here if a
        # repository_metadata record is not returned because repositories of this type will never
        # have repository dependencies. However, if a readme file is uploaded, or some other change
        # is made that does not create a new downloadable changeset revision but updates the existing
        # one, we still want to be able to get repository dependencies.
        repository_metadata = suc.get_current_repository_metadata_for_changeset_revision( trans.app,
                                                                                          repository,
                                                                                          changeset_revision )
        if repository_metadata:
            metadata = repository_metadata.metadata
            if metadata:
                toolshed_base_url = str( web.url_for( '/', qualified=True ) ).rstrip( '/' )
                rb = relation_builder.RelationBuilder( trans.app, repository, repository_metadata, toolshed_base_url )
                repository_dependencies = rb.get_repository_dependencies_for_changeset_revision()
                if repository_dependencies:
                    return encoding_util.tool_shed_encode( repository_dependencies )
        return ''

    @web.expose
    def get_repository_id( self, trans, **kwd ):
        """Given a repository name and owner, return the encoded repository id."""
        repository_name = kwd[ 'name' ]
        repository_owner = kwd[ 'owner' ]
        repository = suc.get_repository_by_name_and_owner( trans.app, repository_name, repository_owner )
        if repository:
            return trans.security.encode_id( repository.id )
        return ''

    @web.json
    def get_repository_information( self, trans, repository_ids, changeset_revisions, **kwd ):
        """
        Generate a list of dictionaries, each of which contains the information about a repository that will
        be necessary for installing it into a local Galaxy instance.
        """
        includes_tools = False
        includes_tools_for_display_in_tool_panel = False
        has_repository_dependencies = False
        has_repository_dependencies_only_if_compiling_contained_td = False
        includes_tool_dependencies = False
        repo_info_dicts = []
        for tup in zip( util.listify( repository_ids ), util.listify( changeset_revisions ) ):
            repository_id, changeset_revision = tup
            repo_info_dict, cur_includes_tools, cur_includes_tool_dependencies, cur_includes_tools_for_display_in_tool_panel, \
                cur_has_repository_dependencies, cur_has_repository_dependencies_only_if_compiling_contained_td = \
                repository_util.get_repo_info_dict( trans.app, trans.user, repository_id, changeset_revision )
            if cur_has_repository_dependencies and not has_repository_dependencies:
                has_repository_dependencies = True
            if cur_has_repository_dependencies_only_if_compiling_contained_td and not has_repository_dependencies_only_if_compiling_contained_td:
                has_repository_dependencies_only_if_compiling_contained_td = True
            if cur_includes_tools and not includes_tools:
                includes_tools = True
            if cur_includes_tool_dependencies and not includes_tool_dependencies:
                includes_tool_dependencies = True
            if cur_includes_tools_for_display_in_tool_panel and not includes_tools_for_display_in_tool_panel:
                includes_tools_for_display_in_tool_panel = True
            repo_info_dicts.append( encoding_util.tool_shed_encode( repo_info_dict ) )
        return dict( includes_tools=includes_tools,
                     includes_tools_for_display_in_tool_panel=includes_tools_for_display_in_tool_panel,
                     has_repository_dependencies=has_repository_dependencies,
                     has_repository_dependencies_only_if_compiling_contained_td=has_repository_dependencies_only_if_compiling_contained_td,
                     includes_tool_dependencies=includes_tool_dependencies,
                     repo_info_dicts=repo_info_dicts )

    @web.json
    def get_required_repo_info_dict( self, trans, encoded_str=None ):
        """
        Retrieve and return a dictionary that includes a list of dictionaries that each contain all of the
        information needed to install the list of repositories defined by the received encoded_str.
        """
        repo_info_dict = {}
        if encoded_str:
            encoded_required_repository_str = encoding_util.tool_shed_decode( encoded_str )
            encoded_required_repository_tups = encoded_required_repository_str.split( encoding_util.encoding_sep2 )
            decoded_required_repository_tups = []
            for encoded_required_repository_tup in encoded_required_repository_tups:
                decoded_required_repository_tups.append( encoded_required_repository_tup.split( encoding_util.encoding_sep ) )
            encoded_repository_ids = []
            changeset_revisions = []
            for required_repository_tup in decoded_required_repository_tups:
                tool_shed, name, owner, changeset_revision, prior_installation_required, only_if_compiling_contained_td = \
                    common_util.parse_repository_dependency_tuple( required_repository_tup )
                repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
                encoded_repository_ids.append( trans.security.encode_id( repository.id ) )
                changeset_revisions.append( changeset_revision )
            if encoded_repository_ids and changeset_revisions:
                repo_info_dict = json.loads( self.get_repository_information( trans, encoded_repository_ids, changeset_revisions ) )
        return repo_info_dict

    @web.expose
    def get_tool_dependencies( self, trans, **kwd ):
        """
        Handle a request from a Galaxy instance to get the tool_dependencies entry from the metadata
        for a specified changeset revision.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        for downloadable_revision in repository.downloadable_revisions:
            if downloadable_revision.changeset_revision == changeset_revision:
                break
        metadata = downloadable_revision.metadata
        tool_dependencies = metadata.get( 'tool_dependencies', '' )
        if tool_dependencies:
            return encoding_util.tool_shed_encode( tool_dependencies )
        return ''

    @web.expose
    def get_tool_dependencies_config_contents( self, trans, **kwd ):
        """
        Handle a request from a Galaxy instance to get the tool_dependencies.xml file contents for a
        specified changeset revision.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        # TODO: We're currently returning the tool_dependencies.xml file that is available on disk.  We need
        # to enhance this process to retrieve older versions of the tool-dependencies.xml file from the repository
        #manafest.
        repo_dir = repository.repo_path( trans.app )
        # Get the tool_dependencies.xml file from disk.
        tool_dependencies_config = hg_util.get_config_from_disk( rt_util.TOOL_DEPENDENCY_DEFINITION_FILENAME, repo_dir )
        # Return the encoded contents of the tool_dependencies.xml file.
        if tool_dependencies_config:
            tool_dependencies_config_file = open( tool_dependencies_config, 'rb' )
            contents = tool_dependencies_config_file.read()
            tool_dependencies_config_file.close()
            return contents
        return ''

    @web.expose
    def get_tool_versions( self, trans, **kwd ):
        """
        For each valid /downloadable change set (up to the received changeset_revision) in the repository's
        change log, append the changeset tool_versions dictionary to the list that will be returned.
        """
        name = kwd[ 'name' ]
        owner = kwd[ 'owner' ]
        changeset_revision = kwd[ 'changeset_revision' ]
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        tool_version_dicts = []
        for changeset in repo.changelog:
            current_changeset_revision = str( repo.changectx( changeset ) )
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                     trans.security.encode_id( repository.id ),
                                                                                     current_changeset_revision )
            if repository_metadata and repository_metadata.tool_versions:
                tool_version_dicts.append( repository_metadata.tool_versions )
                if current_changeset_revision == changeset_revision:
                    break
        if tool_version_dicts:
            return json.dumps( tool_version_dicts )
        return ''

    @web.json
    def get_updated_repository_information( self, trans, name, owner, changeset_revision, **kwd ):
        """
        Generate a dictionary that contains the information about a repository that is necessary for installing
        it into a local Galaxy instance.
        """
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        repository_id = trans.security.encode_id( repository.id )
        repository_clone_url = common_util.generate_clone_url_for_repository_in_tool_shed( trans.user, repository )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, repository_id, changeset_revision )
        if not repository_metadata:
            # The received changeset_revision is no longer associated with metadata, so get the next changeset_revision in the repository
            # changelog that is associated with metadata.
            changeset_revision = suc.get_next_downloadable_changeset_revision( repository,
                                                                               repo,
                                                                               after_changeset_revision=changeset_revision )
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, repository_id, changeset_revision )
        ctx = hg_util.get_changectx_for_changeset( repo, changeset_revision )
        repo_info_dict = repository_util.create_repo_info_dict( app=trans.app,
                                                                repository_clone_url=repository_clone_url,
                                                                changeset_revision=changeset_revision,
                                                                ctx_rev=str( ctx.rev() ),
                                                                repository_owner=repository.user.username,
                                                                repository_name=repository.name,
                                                                repository=repository,
                                                                repository_metadata=repository_metadata,
                                                                tool_dependencies=None,
                                                                repository_dependencies=None )
        includes_data_managers = False
        includes_datatypes = False
        includes_tools = False
        includes_tools_for_display_in_tool_panel = False
        includes_workflows = False
        readme_files_dict = None
        metadata = repository_metadata.metadata
        if metadata:
            if 'data_manager' in metadata:
                includes_data_managers = True
            if 'datatypes' in metadata:
                includes_datatypes = True
            if 'tools' in metadata:
                includes_tools = True
                # Handle includes_tools_for_display_in_tool_panel.
                tool_dicts = metadata[ 'tools' ]
                for tool_dict in tool_dicts:
                    if tool_dict.get( 'includes_tools_for_display_in_tool_panel', False ):
                        includes_tools_for_display_in_tool_panel = True
                        break
            if 'workflows' in metadata:
                includes_workflows = True
            readme_files_dict = readme_util.build_readme_files_dict( trans.app, repository, changeset_revision, metadata )
        # See if the repo_info_dict was populated with repository_dependencies or tool_dependencies.
        has_repository_dependencies = False
        has_repository_dependencies_only_if_compiling_contained_td = False
        includes_tool_dependencies = False
        for name, repo_info_tuple in repo_info_dict.items():
            if not has_repository_dependencies or not has_repository_dependencies_only_if_compiling_contained_td or not includes_tool_dependencies:
                description, repository_clone_url, changeset_revision, ctx_rev, repository_owner, repository_dependencies, tool_dependencies = \
                    suc.get_repo_info_tuple_contents( repo_info_tuple )
                for rd_key, rd_tups in repository_dependencies.items():
                    if rd_key in [ 'root_key', 'description' ]:
                        continue
                    curr_has_repository_dependencies, curr_has_repository_dependencies_only_if_compiling_contained_td = \
                        suc.get_repository_dependency_types( rd_tups )
                    if curr_has_repository_dependencies and not has_repository_dependencies:
                        has_repository_dependencies = True
                    if curr_has_repository_dependencies_only_if_compiling_contained_td and not has_repository_dependencies_only_if_compiling_contained_td:
                        has_repository_dependencies_only_if_compiling_contained_td = True
                if tool_dependencies and not includes_tool_dependencies:
                    includes_tool_dependencies = True
        return dict( includes_data_managers=includes_data_managers,
                     includes_datatypes=includes_datatypes,
                     includes_tools=includes_tools,
                     includes_tools_for_display_in_tool_panel=includes_tools_for_display_in_tool_panel,
                     has_repository_dependencies=has_repository_dependencies,
                     has_repository_dependencies_only_if_compiling_contained_td=has_repository_dependencies_only_if_compiling_contained_td,
                     includes_tool_dependencies=includes_tool_dependencies,
                     includes_workflows=includes_workflows,
                     readme_files_dict=readme_files_dict,
                     repo_info_dict=repo_info_dict )

    @web.expose
    def help( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        return trans.fill_template( '/webapps/tool_shed/repository/help.mako', message=message, status=status, **kwd )

    @web.expose
    def import_capsule( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        capsule_file_name = kwd.get( 'capsule_file_name', None )
        encoded_file_path = kwd.get( 'encoded_file_path', None )
        file_path = encoding_util.tool_shed_decode( encoded_file_path )
        export_info_file_path = os.path.join( file_path, 'export_info.xml' )
        irm = capsule_manager.ImportRepositoryManager( trans.app,
                                                       trans.request.host,
                                                       trans.user,
                                                       trans.user_is_admin() )
        export_info_dict = irm.get_export_info_dict( export_info_file_path )
        manifest_file_path = os.path.join( file_path, 'manifest.xml' )
        # The manifest.xml file has already been validated, so no error_message should be returned here.
        repository_info_dicts, error_message = irm.get_repository_info_from_manifest( manifest_file_path )
        # Determine the status for each exported repository archive contained within the capsule.
        repository_status_info_dicts = irm.get_repository_status_from_tool_shed( repository_info_dicts )
        if 'import_capsule_button' in kwd:
            # Generate a list of repository name / import results message tuples for display after the capsule is imported.
            import_results_tups = []
            # Only create repositories that do not yet exist and that the current user is authorized to create.  The
            # status will be None for repositories that fall into the intersection of these 2 categories.
            for repository_status_info_dict in repository_status_info_dicts:
                # Add the capsule_file_name and encoded_file_path to the repository_status_info_dict.
                repository_status_info_dict[ 'capsule_file_name' ] = capsule_file_name
                repository_status_info_dict[ 'encoded_file_path' ] = encoded_file_path
                import_results_tups = irm.create_repository_and_import_archive( repository_status_info_dict,
                                                                                import_results_tups )
            irm.check_status_and_reset_downloadable( import_results_tups )
            basic_util.remove_dir( file_path )
            return trans.fill_template( '/webapps/tool_shed/repository/import_capsule_results.mako',
                                        export_info_dict=export_info_dict,
                                        import_results_tups=import_results_tups,
                                        message=message,
                                        status=status )
        return trans.fill_template( '/webapps/tool_shed/repository/import_capsule.mako',
                                    encoded_file_path=encoded_file_path,
                                    export_info_dict=export_info_dict,
                                    repository_status_info_dicts=repository_status_info_dicts,
                                    message=message,
                                    status=status )

    @web.expose
    def index( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        # See if there are any RepositoryMetadata records since menu items require them.
        repository_metadata = trans.sa_session.query( trans.model.RepositoryMetadata ).first()
        current_user = trans.user
        # TODO: move the following to some in-memory register so these queries can be done once
        # at startup.  The in-memory register can then be managed during the current session.
        can_administer_repositories = False
        has_reviewed_repositories = False
        has_deprecated_repositories = False
        if current_user:
            # See if the current user owns any repositories that have been reviewed.
            for repository in current_user.active_repositories:
                if repository.reviews:
                    has_reviewed_repositories = True
                    break
            # See if the current user has any repositories that have been marked as deprecated.
            for repository in current_user.active_repositories:
                if repository.deprecated:
                    has_deprecated_repositories = True
                    break
            # See if the current user can administer any repositories, but only if not an admin user.
            if not trans.user_is_admin():
                if current_user.active_repositories:
                    can_administer_repositories = True
                else:
                    for repository in trans.sa_session.query( trans.model.Repository ) \
                                                      .filter( trans.model.Repository.table.c.deleted == False ):
                        if trans.app.security_agent.user_can_administer_repository( current_user, repository ):
                            can_administer_repositories = True
                            break
        # Route in may have been from a sharable URL, in whcih case we'll have a user_id and possibly a name
        # The received user_id will be the id of the repository owner.
        user_id = kwd.get( 'user_id', None )
        repository_id = kwd.get( 'repository_id', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        return trans.fill_template( '/webapps/tool_shed/index.mako',
                                    repository_metadata=repository_metadata,
                                    can_administer_repositories=can_administer_repositories,
                                    has_reviewed_repositories=has_reviewed_repositories,
                                    has_deprecated_repositories=has_deprecated_repositories,
                                    user_id=user_id,
                                    repository_id=repository_id,
                                    changeset_revision=changeset_revision,
                                    message=message,
                                    status=status )

    @web.expose
    def install_repositories_by_revision( self, trans, **kwd ):
        """
        Send the list of repository_ids and changeset_revisions to Galaxy so it can begin the installation
        process.  If the value of repository_ids is not received, then the name and owner of a single repository
        must be received to install a single repository.
        """
        repository_ids = kwd.get( 'repository_ids', None )
        changeset_revisions = kwd.get( 'changeset_revisions', None )
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        if not repository_ids:
            repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
            repository_ids = trans.security.encode_id( repository.id )
        galaxy_url = common_util.handle_galaxy_url( trans, **kwd )
        if galaxy_url:
            # Redirect back to local Galaxy to perform install.
            params = '?tool_shed_url=%s&repository_ids=%s&changeset_revisions=%s' % \
                ( web.url_for( '/', qualified=True ),
                  ','.join( util.listify( repository_ids ) ),
                  ','.join( util.listify( changeset_revisions ) ) )
            url = common_util.url_join( galaxy_url,
                                        'admin_toolshed/prepare_for_install%s' % params )
            return trans.response.send_redirect( url )
        else:
            message = 'Repository installation is not possible due to an invalid Galaxy URL: <b>%s</b>.  '  % galaxy_url
            message += 'You may need to enable third-party cookies in your browser.  '
            status = 'error'
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_valid_categories',
                                                              message=message,
                                                              status=status ) )

    @web.expose
    def load_invalid_tool( self, trans, repository_id, tool_config, changeset_revision, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'error' )
        render_repository_actions_for = kwd.get( 'render_repository_actions_for', 'tool_shed' )
        tv = tool_validator.ToolValidator( trans.app )
        repository, tool, error_message = tv.load_tool_from_changeset_revision( repository_id,
                                                                                changeset_revision,
                                                                                tool_config )
        tool_state = tool_util.new_state( trans, tool, invalid=True )
        invalid_file_tups = []
        if tool:
            invalid_file_tups = tv.check_tool_input_params( repository.repo_path( trans.app ),
                                                            tool_config,
                                                            tool,
                                                            [] )
        if invalid_file_tups:
            message = tool_util.generate_message_for_invalid_tools( trans.app,
                                                                    invalid_file_tups,
                                                                    repository,
                                                                    {},
                                                                    as_html=True,
                                                                    displaying_invalid_tool=True )
        elif error_message:
            message = error_message
        try:
            return trans.fill_template( "/webapps/tool_shed/repository/tool_form.mako",
                                        repository=repository,
                                        render_repository_actions_for=render_repository_actions_for,
                                        changeset_revision=changeset_revision,
                                        tool=tool,
                                        tool_state=tool_state,
                                        message=message,
                                        status='error' )
        except Exception, e:
            message = "Exception thrown attempting to display tool: %s." % str( e )
        if trans.webapp.name == 'galaxy':
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='preview_tools_in_changeset',
                                                              repository_id=repository_id,
                                                              changeset_revision=changeset_revision,
                                                              message=message,
                                                              status='error' ) )
        return trans.response.send_redirect( web.url_for( controller='repository',
                                                          action='browse_repositories',
                                                          operation='view_or_manage_repository',
                                                          id=repository_id,
                                                          changeset_revision=changeset_revision,
                                                          message=message,
                                                          status='error' ) )

    @web.expose
    @web.require_login( "manage email alerts" )
    def manage_email_alerts( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        new_repo_alert = kwd.get( 'new_repo_alert', '' )
        new_repo_alert_checked = CheckboxField.is_checked( new_repo_alert )
        user = trans.user
        if kwd.get( 'new_repo_alert_button', False ):
            user.new_repo_alert = new_repo_alert_checked
            trans.sa_session.add( user )
            trans.sa_session.flush()
            if new_repo_alert_checked:
                message = 'You will receive email alerts for all new valid tool shed repositories.'
            else:
                message = 'You will not receive any email alerts for new valid tool shed repositories.'
        checked = new_repo_alert_checked or ( user and user.new_repo_alert )
        new_repo_alert_check_box = CheckboxField( 'new_repo_alert', checked=checked )
        email_alert_repositories = []
        for repository in trans.sa_session.query( trans.model.Repository ) \
                                          .filter( and_( trans.model.Repository.table.c.deleted == False,
                                                         trans.model.Repository.table.c.email_alerts != None ) ) \
                                          .order_by( trans.model.Repository.table.c.name ):
            if user.email in repository.email_alerts:
                email_alert_repositories.append( repository )
        return trans.fill_template( "/webapps/tool_shed/user/manage_email_alerts.mako",
                                    new_repo_alert_check_box=new_repo_alert_check_box,
                                    email_alert_repositories=email_alert_repositories,
                                    message=message,
                                    status=status )

    @web.expose
    @web.require_login( "manage repository" )
    def manage_repository( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        repository_type = kwd.get( 'repository_type', str( repository.type ) )
        repo_dir = repository.repo_path( trans.app )
        repo = hg_util.get_repo_for_repository( trans.app, repository=None, repo_path=repo_dir, create=False )
        repo_name = kwd.get( 'repo_name', repository.name )
        changeset_revision = kwd.get( 'changeset_revision', repository.tip( trans.app ) )
        repository.share_url = suc.generate_sharable_link_for_repository_in_tool_shed( repository, changeset_revision=changeset_revision )
        repository.clone_url = common_util.generate_clone_url_for_repository_in_tool_shed( trans.user, repository )
        remote_repository_url = kwd.get( 'remote_repository_url', repository.remote_repository_url )
        homepage_url = kwd.get( 'homepage_url', repository.homepage_url )
        description = kwd.get( 'description', repository.description )
        long_description = kwd.get( 'long_description', repository.long_description )
        avg_rating, num_ratings = self.get_ave_item_rating_data( trans.sa_session, repository, webapp_model=trans.model )
        display_reviews = util.string_as_bool( kwd.get( 'display_reviews', False ) )
        alerts = kwd.get( 'alerts', '' )
        alerts_checked = CheckboxField.is_checked( alerts )
        skip_tool_tests = kwd.get( 'skip_tool_tests', '' )
        skip_tool_tests_checked = CheckboxField.is_checked( skip_tool_tests )
        skip_tool_tests_comment = kwd.get( 'skip_tool_tests_comment', '' )
        category_ids = util.listify( kwd.get( 'category_id', '' ) )
        if repository.email_alerts:
            email_alerts = json.loads( repository.email_alerts )
        else:
            email_alerts = []
        allow_push = kwd.get( 'allow_push', '' )
        error = False
        user = trans.user
        if kwd.get( 'edit_repository_button', False ):
            update_kwds = dict(
                name=repo_name,
                description=description,
                long_description=long_description,
                remote_repository_url=remote_repository_url,
                homepage_url=homepage_url,
                type=repository_type,
            )

            repository, message = repository_util.update_repository( app=trans.app, trans=trans, id=id, **update_kwds )
            if repository is None:
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_repository',
                                                                  id=id,
                                                                  message=message,
                                                                  status='error' ) )

        elif kwd.get( 'skip_tool_tests_button', False ):
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, id, changeset_revision )
            skip_tool_test = repository_metadata.skip_tool_tests
            if skip_tool_test:
                # Handle the mapper behavior.
                skip_tool_test = skip_tool_test[ 0 ]
            if skip_tool_tests_checked:
                if repository_metadata.tool_test_results:
                    repository_metadata.tool_test_results = None
                    trans.sa_session.add( repository_metadata )
                    trans.sa_session.flush()
                if skip_tool_test:
                    comment = skip_tool_test.comment
                    if comment != skip_tool_tests_comment:
                        skip_tool_test.comment = skip_tool_tests_comment
                        trans.sa_session.add( skip_tool_test )
                        trans.sa_session.flush()
                else:
                    skip_tool_test = trans.model.SkipToolTest( repository_metadata_id=repository_metadata.id,
                                                               initial_changeset_revision=changeset_revision,
                                                               comment=skip_tool_tests_comment )
                    trans.sa_session.add( skip_tool_test )
                    trans.sa_session.flush()
                message = "Tools in this revision will not be tested by the automated test framework."
            else:
                if skip_tool_test:
                    trans.sa_session.delete( skip_tool_test )
                    trans.sa_session.flush()
                message = "Tools in this revision will be tested by the automated test framework."
        elif kwd.get( 'manage_categories_button', False ):
            flush_needed = False
            # Delete all currently existing categories.
            for rca in repository.categories:
                trans.sa_session.delete( rca )
                trans.sa_session.flush()
            if category_ids:
                # Create category associations
                for category_id in category_ids:
                    category = trans.sa_session.query( trans.model.Category ).get( trans.security.decode_id( category_id ) )
                    rca = trans.app.model.RepositoryCategoryAssociation( repository, category )
                    trans.sa_session.add( rca )
                    trans.sa_session.flush()
            message = "The repository information has been updated."
        elif kwd.get( 'user_access_button', False ):
            if allow_push not in [ 'none' ]:
                remove_auth = kwd.get( 'remove_auth', '' )
                if remove_auth:
                    usernames = ''
                else:
                    user_ids = util.listify( allow_push )
                    usernames = []
                    for user_id in user_ids:
                        user = trans.sa_session.query( trans.model.User ).get( trans.security.decode_id( user_id ) )
                        usernames.append( user.username )
                    usernames = ','.join( usernames )
                repository.set_allow_push( trans.app, usernames, remove_auth=remove_auth )
            message = "The repository information has been updated."
        elif kwd.get( 'receive_email_alerts_button', False ):
            flush_needed = False
            if alerts_checked:
                if user.email not in email_alerts:
                    email_alerts.append( user.email )
                    repository.email_alerts = json.dumps( email_alerts )
                    flush_needed = True
            else:
                if user.email in email_alerts:
                    email_alerts.remove( user.email )
                    repository.email_alerts = json.dumps( email_alerts )
                    flush_needed = True
            if flush_needed:
                trans.sa_session.add( repository )
                trans.sa_session.flush()
            message = "The repository information has been updated."
        if error:
            status = 'error'
        current_allow_push = repository.allow_push( trans.app )
        if current_allow_push:
            current_allow_push_list = current_allow_push.split( ',' )
        else:
            current_allow_push_list = []
        allow_push_select_field = repository_util.build_allow_push_select_field( trans, current_allow_push_list )
        checked = alerts_checked or user.email in email_alerts
        alerts_check_box = CheckboxField( 'alerts', checked=checked )
        changeset_revision_select_field = grids_util.build_changeset_revision_select_field( trans,
                                                                                            repository,
                                                                                            selected_value=changeset_revision,
                                                                                            add_id_to_name=False,
                                                                                            downloadable=False )
        revision_label = hg_util.get_revision_label( trans.app, repository, repository.tip( trans.app ), include_date=False )
        repository_metadata = None
        metadata = None
        is_malicious = False
        skip_tool_test = None
        repository_dependencies = None
        if changeset_revision != hg_util.INITIAL_CHANGELOG_HASH:
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, id, changeset_revision )
            if repository_metadata:
                revision_label = hg_util.get_revision_label( trans.app, repository, changeset_revision, include_date=False )
                metadata = repository_metadata.metadata
                is_malicious = repository_metadata.malicious
            else:
                # There is no repository_metadata defined for the changeset_revision, so see if it was defined in a previous
                # changeset in the changelog.
                previous_changeset_revision = \
                    metadata_util.get_previous_metadata_changeset_revision( repository, repo, changeset_revision, downloadable=False )
                if previous_changeset_revision != hg_util.INITIAL_CHANGELOG_HASH:
                    repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, id, previous_changeset_revision )
                    if repository_metadata:
                        revision_label = hg_util.get_revision_label( trans.app, repository, previous_changeset_revision, include_date=False )
                        metadata = repository_metadata.metadata
                        is_malicious = repository_metadata.malicious
                        changeset_revision = previous_changeset_revision
            if repository_metadata:
                skip_tool_test = repository_metadata.skip_tool_tests
                if skip_tool_test:
                    # Handle the mapper behavior.
                    skip_tool_test = skip_tool_test[ 0 ]
                    skip_tool_tests_checked = True
                metadata = repository_metadata.metadata
                # Get a dictionary of all repositories upon which the contents of the current repository_metadata record depend.
                toolshed_base_url = str( web.url_for( '/', qualified=True ) ).rstrip( '/' )
                rb = relation_builder.RelationBuilder( trans.app, repository, repository_metadata, toolshed_base_url )
                repository_dependencies = rb.get_repository_dependencies_for_changeset_revision()
                if str( repository.type ) != rt_util.REPOSITORY_SUITE_DEFINITION:
                    # Handle messaging for resetting repository type to the optimal value.
                    change_repository_type_message = rt_util.generate_message_for_repository_type_change( trans.app,
                                                                                                          repository )
                    if change_repository_type_message:
                        message += change_repository_type_message
                        status = 'warning'
                elif str( repository.type ) != rt_util.TOOL_DEPENDENCY_DEFINITION:
                    # Handle messaging for resetting repository type to the optimal value.
                    change_repository_type_message = rt_util.generate_message_for_repository_type_change( trans.app,
                                                                                                          repository )
                    if change_repository_type_message:
                        message += change_repository_type_message
                        status = 'warning'
                    else:
                        # Handle messaging for orphan tool dependency definitions.
                        dd = dependency_display.DependencyDisplayer( trans.app )
                        orphan_message = dd.generate_message_for_orphan_tool_dependencies( repository, metadata )
                        if orphan_message:
                            message += orphan_message
                            status = 'warning'
        if is_malicious:
            if trans.app.security_agent.can_push( trans.app, trans.user, repository ):
                message += malicious_error_can_push
            else:
                message += malicious_error
            status = 'error'
        repository_type_select_field = rt_util.build_repository_type_select_field( trans, repository=repository )
        malicious_check_box = CheckboxField( 'malicious', checked=is_malicious )
        skip_tool_tests_check_box = CheckboxField( 'skip_tool_tests', checked=skip_tool_tests_checked )
        categories = suc.get_categories( trans.app )
        selected_categories = [ rca.category_id for rca in repository.categories ]
        tsucm = ToolShedUtilityContainerManager( trans.app )
        containers_dict = tsucm.build_repository_containers( repository,
                                                             changeset_revision,
                                                             repository_dependencies,
                                                             repository_metadata )
        heads = hg_util.get_repository_heads( repo )
        deprecated_repository_dependency_tups = \
            metadata_util.get_repository_dependency_tups_from_repository_metadata( trans.app,
                                                                                   repository_metadata,
                                                                                   deprecated_only=True )
        return trans.fill_template( '/webapps/tool_shed/repository/manage_repository.mako',
                                    repo_name=repo_name,
                                    remote_repository_url=remote_repository_url,
                                    homepage_url=homepage_url,
                                    description=description,
                                    long_description=long_description,
                                    current_allow_push_list=current_allow_push_list,
                                    allow_push_select_field=allow_push_select_field,
                                    deprecated_repository_dependency_tups=deprecated_repository_dependency_tups,
                                    repo=repo,
                                    heads=heads,
                                    repository=repository,
                                    containers_dict=containers_dict,
                                    repository_metadata=repository_metadata,
                                    changeset_revision=changeset_revision,
                                    changeset_revision_select_field=changeset_revision_select_field,
                                    revision_label=revision_label,
                                    selected_categories=selected_categories,
                                    categories=categories,
                                    metadata=metadata,
                                    avg_rating=avg_rating,
                                    display_reviews=display_reviews,
                                    num_ratings=num_ratings,
                                    alerts_check_box=alerts_check_box,
                                    skip_tool_tests_check_box=skip_tool_tests_check_box,
                                    skip_tool_test=skip_tool_test,
                                    malicious_check_box=malicious_check_box,
                                    repository_type_select_field=repository_type_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    @web.require_login( "manage repository administrators" )
    def manage_repository_admins( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        changeset_revision = kwd.get( 'changeset_revision', repository.tip( trans.app ) )
        metadata = None
        if changeset_revision != hg_util.INITIAL_CHANGELOG_HASH:
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, id, changeset_revision )
            if repository_metadata:
                metadata = repository_metadata.metadata
            else:
                # There is no repository_metadata defined for the changeset_revision, so see if it was defined
                # in a previous changeset in the changelog.
                repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
                previous_changeset_revision = \
                    metadata_util.get_previous_metadata_changeset_revision( repository,
                                                                            repo,
                                                                            changeset_revision,
                                                                            downloadable=False )
                if previous_changeset_revision != hg_util.INITIAL_CHANGELOG_HASH:
                    repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                             id,
                                                                                             previous_changeset_revision )
                    if repository_metadata:
                        metadata = repository_metadata.metadata
        role = repository.admin_role
        associations_dict = repository_util.handle_role_associations( trans.app,
                                                                      role,
                                                                      repository,
                                                                      **kwd )
        in_users = associations_dict.get( 'in_users', [] )
        out_users = associations_dict.get( 'out_users', [] )
        in_groups = associations_dict.get( 'in_groups', [] )
        out_groups = associations_dict.get( 'out_groups', [] )
        message = associations_dict.get( 'message', '' )
        status = associations_dict.get( 'status', 'done' )
        return trans.fill_template( '/webapps/tool_shed/role/role.mako',
                                    in_admin_controller=False,
                                    repository=repository,
                                    metadata=metadata,
                                    changeset_revision=changeset_revision,
                                    role=role,
                                    in_users=in_users,
                                    out_users=out_users,
                                    in_groups=in_groups,
                                    out_groups=out_groups,
                                    message=message,
                                    status=status )

    @web.expose
    @web.require_login( "review repository revision" )
    def manage_repository_reviews_of_revision( self, trans, **kwd ):
        return trans.response.send_redirect( web.url_for( controller='repository_review',
                                                          action='manage_repository_reviews_of_revision',
                                                          **kwd ) )

    @web.expose
    @web.require_login( "multi select email alerts" )
    def multi_select_email_alerts( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        if 'operation' in kwd:
            operation = kwd[ 'operation' ].lower()
            if operation == "receive email alerts":
                if trans.user:
                    if kwd[ 'id' ]:
                        kwd[ 'caller' ] = 'multi_select_email_alerts'
                        return trans.response.send_redirect( web.url_for( controller='repository',
                                                                          action='set_email_alerts',
                                                                          **kwd ) )
                else:
                    kwd[ 'message' ] = 'You must be logged in to set email alerts.'
                    kwd[ 'status' ] = 'error'
                    del kwd[ 'operation' ]
            elif operation == "view_or_manage_repository":
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='view_or_manage_repository',
                                                                  **kwd ) )
        self.email_alerts_repository_grid.title = "Set email alerts for repository changes"
        return self.email_alerts_repository_grid( trans, **kwd )

    @web.expose
    def next_installable_changeset_revision( self, trans, **kwd ):
        """
        Handle a request from a Galaxy instance where the changeset_revision defined for a repository
        in a dependency definition file is older than the changeset_revision associated with the installed
        repository.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        # Get the next installable changeset_revision beyond the received changeset_revision.
        changeset_revision = suc.get_next_downloadable_changeset_revision( repository, repo, changeset_revision )
        if changeset_revision:
            return changeset_revision
        return ''

    @web.json
    def open_folder( self, trans, folder_path ):
        # Avoid caching
        trans.response.headers['Pragma'] = 'no-cache'
        trans.response.headers['Expires'] = '0'
        return suc.open_repository_files_folder( folder_path )

    @web.expose
    def preview_tools_in_changeset( self, trans, repository_id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        changeset_revision = kwd.get( 'changeset_revision', repository.tip( trans.app ) )
        repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, repository_id, changeset_revision )
        if repository_metadata:
            repository_metadata_id = trans.security.encode_id( repository_metadata.id ),
            metadata = repository_metadata.metadata
            # Get a dictionary of all repositories upon which the contents of the current repository_metadata record depend.
            toolshed_base_url = str( web.url_for( '/', qualified=True ) ).rstrip( '/' )
            rb = relation_builder.RelationBuilder( trans.app, repository, repository_metadata, toolshed_base_url )
            repository_dependencies = rb.get_repository_dependencies_for_changeset_revision()
            if metadata:
                if 'repository_dependencies' in metadata and not repository_dependencies:
                    # See if we have an invalid repository dependency definition or if the repository dependency is required
                    # only for compiling the repository's tool dependency.
                    invalid = False
                    repository_dependencies_dict = metadata[ 'repository_dependencies' ]
                    rd_tups = repository_dependencies_dict.get( 'repository_dependencies', [] )
                    for rd_tup in rd_tups:
                        rdtool_shed, \
                        rd_name, \
                        rd_owner, \
                        rd_changeset_revision, \
                        rd_prior_installation_required, \
                        rd_only_if_compiling_contained_td = \
                            common_util.parse_repository_dependency_tuple( rd_tup )
                        if not util.asbool( rd_only_if_compiling_contained_td ):
                            invalid = True
                            break
                    if invalid:
                        dd = dependency_display.DependencyDisplayer( trans.app )
                        message = dd.generate_message_for_invalid_repository_dependencies( metadata,
                                                                                           error_from_tuple=False )
                        status = 'error'
        else:
            repository_metadata_id = None
            metadata = None
            repository_dependencies = None
        revision_label = hg_util.get_revision_label( trans.app, repository, changeset_revision, include_date=True )
        changeset_revision_select_field = grids_util.build_changeset_revision_select_field( trans,
                                                                                            repository,
                                                                                            selected_value=changeset_revision,
                                                                                            add_id_to_name=False,
                                                                                            downloadable=False )
        tsucm = ToolShedUtilityContainerManager( trans.app )
        containers_dict = tsucm.build_repository_containers( repository,
                                                             changeset_revision,
                                                             repository_dependencies,
                                                             repository_metadata )
        return trans.fill_template( '/webapps/tool_shed/repository/preview_tools_in_changeset.mako',
                                    repository=repository,
                                    containers_dict=containers_dict,
                                    repository_metadata_id=repository_metadata_id,
                                    changeset_revision=changeset_revision,
                                    revision_label=revision_label,
                                    changeset_revision_select_field=changeset_revision_select_field,
                                    metadata=metadata,
                                    message=message,
                                    status=status )

    @web.expose
    def previous_changeset_revisions( self, trans, from_tip=False, **kwd ):
        """
        Handle a request from a local Galaxy instance.  This method will handle two scenarios: (1) the
        repository was previously installed using an older changeset_revsion, but later the repository
        was updated in the tool shed and the Galaxy admin is trying to install the latest changeset
        revision of the same repository instead of updating the one that was previously installed. (2)
        the admin is attempting to get updates for an installed repository that has a repository dependency
        and both the repository and its dependency have available updates.  In this case, the from_tip
        parameter will be True because the repository dependency definition may define a changeset hash
        for the dependency that is newer than the installed changeset revision of the dependency (this is
        due to the behavior of "Tool dependency definition" repositories, whose metadata is always the tip),
        so the complete list of changset hashes in the changelog must be returned.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        if name is not None and owner is not None:
            repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
            from_tip = util.string_as_bool( from_tip )
            if from_tip:
                changeset_revision = repository.tip( trans.app )
            else:
                changeset_revision = kwd.get( 'changeset_revision', None )
            if changeset_revision is not None:
                repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
                # Get the lower bound changeset revision.
                lower_bound_changeset_revision = metadata_util.get_previous_metadata_changeset_revision( repository,
                                                                                                         repo,
                                                                                                         changeset_revision,
                                                                                                         downloadable=True )
                # Build the list of changeset revision hashes.
                changeset_hashes = []
                for changeset in hg_util.reversed_lower_upper_bounded_changelog( repo,
                                                                                 lower_bound_changeset_revision,
                                                                                 changeset_revision ):
                    changeset_hashes.append( str( repo.changectx( changeset ) ) )
                if changeset_hashes:
                    changeset_hashes_str = ','.join( changeset_hashes )
                    return changeset_hashes_str
        return ''

    @web.expose
    @web.require_login( "rate repositories" )
    def rate_repository( self, trans, **kwd ):
        """ Rate a repository and return updated rating data. """
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        id = kwd.get( 'id', None )
        if not id:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              message='Select a repository to rate',
                                                              status='error' ) )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        changeset_revision = repository.tip( trans.app )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        if repository.user == trans.user:
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='browse_repositories',
                                                              message="You are not allowed to rate your own repository",
                                                              status='error' ) )
        if kwd.get( 'rate_button', False ):
            rating = int( kwd.get( 'rating', '0' ) )
            comment = kwd.get( 'comment', '' )
            rating = self.rate_item( trans, trans.user, repository, rating, comment )
        avg_rating, num_ratings = self.get_ave_item_rating_data( trans.sa_session, repository, webapp_model=trans.model )
        display_reviews = util.string_as_bool( kwd.get( 'display_reviews', False ) )
        rra = self.get_user_item_rating( trans.sa_session, trans.user, repository, webapp_model=trans.model )
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              id,
                                                                                              changeset_revision,
                                                                                              metadata_only=True )
        repository_type_select_field = rt_util.build_repository_type_select_field( trans, repository=repository )
        revision_label = hg_util.get_revision_label( trans.app, repository, changeset_revision, include_date=True )
        return trans.fill_template( '/webapps/tool_shed/repository/rate_repository.mako',
                                    repository=repository,
                                    metadata=metadata,
                                    revision_label=revision_label,
                                    avg_rating=avg_rating,
                                    display_reviews=display_reviews,
                                    num_ratings=num_ratings,
                                    rra=rra,
                                    repository_type_select_field=repository_type_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    def reset_all_metadata( self, trans, id, **kwd ):
        """Reset all metadata on the complete changelog for a single repository in the tool shed."""
        # This method is called only from the ~/templates/webapps/tool_shed/repository/manage_repository.mako template.
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        rmm = repository_metadata_manager.RepositoryMetadataManager( app=trans.app,
                                                                     user=trans.user,
                                                                     repository=repository,
                                                                     resetting_all_metadata_on_repository=True )
        rmm.reset_all_metadata_on_repository_in_tool_shed()
        rmm_metadata_dict = rmm.get_metadata_dict()
        rmm_invalid_file_tups = rmm.get_invalid_file_tups()
        if rmm_invalid_file_tups:
            message = tool_util.generate_message_for_invalid_tools( trans.app,
                                                                    rmm_invalid_file_tups,
                                                                    repository,
                                                                    rmm_metadata_dict )
            status = 'error'
        else:
            message = "All repository metadata has been reset.  "
            status = 'done'
        return trans.response.send_redirect( web.url_for( controller='repository',
                                                          action='manage_repository',
                                                          id=id,
                                                          message=message,
                                                          status=status ) )

    @web.expose
    def reset_metadata_on_my_writable_repositories_in_tool_shed( self, trans, **kwd ):
        rmm = repository_metadata_manager.RepositoryMetadataManager( trans.app, trans.user, resetting_all_metadata_on_repository=True )
        if 'reset_metadata_on_selected_repositories_button' in kwd:
            message, status = rmm.reset_metadata_on_selected_repositories( **kwd )
        else:
            message = escape( kwd.get( 'message', '' ) )
            status = kwd.get( 'status', 'done' )
        repositories_select_field = rmm.build_repository_ids_select_field( name='repository_ids',
                                                                           multiple=True,
                                                                           display='checkboxes',
                                                                           my_writable=True )
        return trans.fill_template( '/webapps/tool_shed/common/reset_metadata_on_selected_repositories.mako',
                                    repositories_select_field=repositories_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    def select_files_to_delete( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        commit_message = escape( kwd.get( 'commit_message', 'Deleted selected files' ) )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        repo_dir = repository.repo_path( trans.app )
        repo = hg_util.get_repo_for_repository( trans.app, repository=None, repo_path=repo_dir, create=False )
        selected_files_to_delete = kwd.get( 'selected_files_to_delete', '' )
        if kwd.get( 'select_files_to_delete_button', False ):
            if selected_files_to_delete:
                selected_files_to_delete = selected_files_to_delete.split( ',' )
                # Get the current repository tip.
                tip = repository.tip( trans.app )
                for selected_file in selected_files_to_delete:
                    try:
                        hg_util.remove_file( repo.ui, repo, selected_file, force=True )
                    except Exception, e:
                        log.debug( "Error removing the following file using the mercurial API:\n %s" % str( selected_file ) )
                        log.debug( "The error was: %s" % str( e ))
                        log.debug( "Attempting to remove the file using a different approach." )
                        relative_selected_file = selected_file.split( 'repo_%d' % repository.id )[1].lstrip( '/' )
                        repo.dirstate.remove( relative_selected_file )
                        repo.dirstate.write()
                        absolute_selected_file = os.path.abspath( selected_file )
                        if os.path.isdir( absolute_selected_file ):
                            try:
                                os.rmdir( absolute_selected_file )
                            except OSError, e:
                                # The directory is not empty
                                pass
                        elif os.path.isfile( absolute_selected_file ):
                            os.remove( absolute_selected_file )
                            dir = os.path.split( absolute_selected_file )[0]
                            try:
                                os.rmdir( dir )
                            except OSError, e:
                                # The directory is not empty
                                pass
                # Commit the change set.
                if not commit_message:
                    commit_message = 'Deleted selected files'
                hg_util.commit_changeset( repo.ui,
                                          repo,
                                          full_path_to_changeset=repo_dir,
                                          username=trans.user.username,
                                          message=commit_message )
                suc.handle_email_alerts( trans.app, trans.request.host, repository )
                # Update the repository files for browsing.
                hg_util.update_repository( repo )
                # Get the new repository tip.
                if tip == repository.tip( trans.app ):
                    message += 'No changes to repository.  '
                else:
                    rmm = repository_metadata_manager.RepositoryMetadataManager( app=trans.app,
                                                                                 user=trans.user,
                                                                                 repository=repository )
                    status, error_message = rmm.set_repository_metadata_due_to_new_tip( trans.request.host, **kwd )
                    if error_message:
                        message = error_message
                    else:
                        message += 'The selected files were deleted from the repository.  '
            else:
                message = "Select at least 1 file to delete from the repository before clicking <b>Delete selected files</b>."
                status = "error"
        repository_type_select_field = rt_util.build_repository_type_select_field( trans, repository=repository )
        changeset_revision = repository.tip( trans.app )
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              id,
                                                                                              changeset_revision,
                                                                                              metadata_only=True )
        return trans.fill_template( '/webapps/tool_shed/repository/browse_repository.mako',
                                    repo=repo,
                                    repository=repository,
                                    changeset_revision=changeset_revision,
                                    metadata=metadata,
                                    commit_message=commit_message,
                                    repository_type_select_field=repository_type_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    def send_to_owner( self, trans, id, message='' ):
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        if not message:
            message = 'Enter a message'
            status = 'error'
        elif trans.user and trans.user.email:
            smtp_server = trans.app.config.smtp_server
            from_address = trans.app.config.email_from
            if smtp_server is None or from_address is None:
                return trans.show_error_message( "Mail is not configured for this Galaxy tool shed instance" )
            to_address = repository.user.email
            # Get the name of the server hosting the tool shed instance.
            host = trans.request.host
            # Build the email message
            body = string.Template( suc.contact_owner_template ) \
                .safe_substitute( username=trans.user.username,
                                  repository_name=repository.name,
                                  email=trans.user.email,
                                  message=message,
                                  host=host )
            subject = "Regarding your tool shed repository named %s" % repository.name
            # Send it
            try:
                util.send_mail( from_address, to_address, subject, body, trans.app.config )
                message = "Your message has been sent"
                status = "done"
            except Exception, e:
                message = "An error occurred sending your message by email: %s" % str( e )
                status = "error"
        else:
            # Do all we can to eliminate spam.
            return trans.show_error_message( "You must be logged in to contact the owner of a repository." )
        return trans.response.send_redirect( web.url_for( controller='repository',
                                                          action='contact_owner',
                                                          id=id,
                                                          message=message,
                                                          status=status ) )

    @web.expose
    @web.require_login( "set email alerts" )
    def set_email_alerts( self, trans, **kwd ):
        """Set email alerts for selected repositories."""
        # This method is called from multiple grids, so the caller must be passed.
        caller = kwd[ 'caller' ]
        user = trans.user
        if user:
            repository_ids = util.listify( kwd.get( 'id', '' ) )
            total_alerts_added = 0
            total_alerts_removed = 0
            flush_needed = False
            for repository_id in repository_ids:
                repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
                if repository.email_alerts:
                    email_alerts = json.loads( repository.email_alerts )
                else:
                    email_alerts = []
                if user.email in email_alerts:
                    email_alerts.remove( user.email )
                    repository.email_alerts = json.dumps( email_alerts )
                    trans.sa_session.add( repository )
                    flush_needed = True
                    total_alerts_removed += 1
                else:
                    email_alerts.append( user.email )
                    repository.email_alerts = json.dumps( email_alerts )
                    trans.sa_session.add( repository )
                    flush_needed = True
                    total_alerts_added += 1
            if flush_needed:
                trans.sa_session.flush()
            message = 'Total alerts added: %d, total alerts removed: %d' % ( total_alerts_added, total_alerts_removed )
            kwd[ 'message' ] = message
            kwd[ 'status' ] = 'done'
        del kwd[ 'operation' ]
        return trans.response.send_redirect( web.url_for( controller='repository',
                                                          action=caller,
                                                          **kwd ) )

    @web.expose
    @web.require_login( "set repository as malicious" )
    def set_malicious( self, trans, id, ctx_str, **kwd ):
        malicious = kwd.get( 'malicious', '' )
        if kwd.get( 'malicious_button', False ):
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, id, ctx_str )
            malicious_checked = CheckboxField.is_checked( malicious )
            repository_metadata.malicious = malicious_checked
            trans.sa_session.add( repository_metadata )
            trans.sa_session.flush()
            if malicious_checked:
                message = "The repository tip has been defined as malicious."
            else:
                message = "The repository tip has been defined as <b>not</b> malicious."
            status = 'done'
        return trans.response.send_redirect( web.url_for( controller='repository',
                                                          action='manage_repository',
                                                          id=id,
                                                          changeset_revision=ctx_str,
                                                          malicious=malicious,
                                                          message=message,
                                                          status=status ) )

    @web.expose
    def sharable_owner( self, trans, owner ):
        """Support for sharable URL for each repository owner's tools, e.g. http://example.org/view/owner."""
        try:
            user = suc.get_user_by_username( trans, owner )
        except:
            user = None
        if user:
            user_id = trans.security.encode_id( user.id )
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='index',
                                                              user_id=user_id ) )
        else:
            return trans.show_error_message( "The tool shed <b>%s</b> contains no repositories owned by <b>%s</b>." % \
                                             ( web.url_for( '/', qualified=True ).rstrip( '/' ), str( owner ) ) )

    @web.expose
    def sharable_repository( self, trans, owner, name ):
        """Support for sharable URL for a specified repository, e.g. http://example.org/view/owner/name."""
        try:
            repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        except:
            repository = None
        if repository:
            repository_id = trans.security.encode_id( repository.id )
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='index',
                                                              repository_id=repository_id ) )
        else:
            # If the owner is valid, then show all of their repositories.
            try:
                user = suc.get_user_by_username( trans, owner )
            except:
                user = None
            if user:
                user_id = trans.security.encode_id( user.id )
                message = "This list of repositories owned by <b>%s</b>, does not include one named <b>%s</b>." % ( str( owner ), str( name ) )
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='index',
                                                                  user_id=user_id,
                                                                  message=message,
                                                                  status='error' ) )
            else:
                return trans.show_error_message( "The tool shed <b>%s</b> contains no repositories named <b>%s</b> with owner <b>%s</b>." % \
                                                 ( web.url_for( '/', qualified=True ).rstrip( '/' ), str( name ), str( owner ) ) )

    @web.expose
    def sharable_repository_revision( self, trans, owner, name, changeset_revision ):
        """Support for sharable URL for a specified repository revision, e.g. http://example.org/view/owner/name/changeset_revision."""
        try:
            repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        except:
            repository = None
        if repository:
            repository_id = trans.security.encode_id( repository.id )
            repository_metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                                             repository_id,
                                                                                                             changeset_revision )
            if not repository_metadata:
                # Get updates to the received changeset_revision if any exist.
                repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
                upper_bound_changeset_revision = suc.get_next_downloadable_changeset_revision( repository, repo, changeset_revision )
                if upper_bound_changeset_revision:
                    changeset_revision = upper_bound_changeset_revision
                    repository_metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                                                     repository_id,
                                                                                                                     changeset_revision )
            if repository_metadata:
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='index',
                                                                  repository_id=repository_id,
                                                                  changeset_revision=changeset_revision ) )
            else:
                message = "The change log for the repository named <b>%s</b> owned by <b>%s</b> does not include revision <b>%s</b>." % \
                    ( escape( str( name ) ), escape( str( owner ) ), escape( str( changeset_revision ) ) )
                return trans.response.send_redirect( web.url_for( controller='repository',
                                                                  action='index',
                                                                  repository_id=repository_id,
                                                                  message=message,
                                                                  status='error' ) )
        else:
            # See if the owner is valid.
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='sharable_owner',
                                                              owner=owner ) )

    @web.expose
    def status_for_installed_repository( self, trans, **kwd ):
        """
        Handle a request from a local Galaxy instance, returning a dictionary with boolean values for whether there are updates available
        for the repository revision, newer installable revisions available, the revision is the latest installable revision, or if the repository
        is deprecated.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        repository = suc.get_repository_by_name_and_owner( trans.app, name, owner )
        if repository:
            repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app,
                                                                                     trans.security.encode_id( repository.id ),
                                                                                     changeset_revision )
            repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
            tool_shed_status_dict = {}
            # Handle repository deprecation.
            tool_shed_status_dict[ 'repository_deprecated' ] = str( repository.deprecated )
            # Handle latest installable revision.
            if changeset_revision == repository.tip( trans.app ):
                tool_shed_status_dict[ 'latest_installable_revision' ] = 'True'
            else:
                next_installable_revision = suc.get_next_downloadable_changeset_revision( repository, repo, changeset_revision )
                if repository_metadata is None:
                    if next_installable_revision:
                        tool_shed_status_dict[ 'latest_installable_revision' ] = 'True'
                    else:
                        tool_shed_status_dict[ 'latest_installable_revision' ] = 'False'
                else:
                    if next_installable_revision:
                        tool_shed_status_dict[ 'latest_installable_revision' ] = 'False'
                    else:
                        tool_shed_status_dict[ 'latest_installable_revision' ] = 'True'
            # Handle revision updates.
            if changeset_revision == repository.tip( trans.app ):
                tool_shed_status_dict[ 'revision_update' ] = 'False'
            else:
                if repository_metadata is None:
                    tool_shed_status_dict[ 'revision_update' ] = 'True'
                else:
                    tool_shed_status_dict[ 'revision_update' ] = 'False'
            # Handle revision upgrades.
            ordered_metadata_changeset_revisions = suc.get_ordered_metadata_changeset_revisions( repository, repo, downloadable=True )
            num_metadata_revisions = len( ordered_metadata_changeset_revisions )
            for index, metadata_changeset_revision in enumerate( ordered_metadata_changeset_revisions ):
                if index == num_metadata_revisions:
                    tool_shed_status_dict[ 'revision_upgrade' ] = 'False'
                    break
                if metadata_changeset_revision == changeset_revision:
                    if num_metadata_revisions - index > 1:
                        tool_shed_status_dict[ 'revision_upgrade' ] = 'True'
                    else:
                        tool_shed_status_dict[ 'revision_upgrade' ] = 'False'
                    break
            return encoding_util.tool_shed_encode( tool_shed_status_dict )
        return encoding_util.tool_shed_encode( {} )

    @web.expose
    def updated_changeset_revisions( self, trans, **kwd ):
        """
        Handle a request from a local Galaxy instance to retrieve the list of changeset revisions to which an
        installed repository can be updated.  This method will return a string of comma-separated changeset revision
        hashes for all available updates to the received changeset revision.  Among other things , this method
        handles the scenario where an installed tool shed repository's tool_dependency definition file defines a
        changeset revision for a complex repository dependency that is outdated.  In other words, a defined changeset
        revision is older than the current changeset revision for the required repository, making it impossible to
        discover the repository without knowledge of revisions to which it could have been updated.
        """
        name = kwd.get( 'name', None )
        owner = kwd.get( 'owner', None )
        changeset_revision = kwd.get( 'changeset_revision', None )
        if name and owner and changeset_revision:
            return suc.get_updated_changeset_revisions( trans.app, name, owner, changeset_revision )
        return ''

    @web.expose
    def upload_capsule( self, trans, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        url = kwd.get( 'url', '' )
        if 'upload_capsule_button' in kwd:
            irm = capsule_manager.ImportRepositoryManager( trans.app,
                                                           trans.request.host,
                                                           trans.user,
                                                           trans.user_is_admin() )
            capsule_dict = irm.upload_capsule( **kwd )
            status = capsule_dict.get( 'status', 'error' )
            if status == 'error':
                message = capsule_dict.get( 'error_message', '' )
            else:
                capsule_dict = irm.extract_capsule_files( **capsule_dict )
                capsule_dict = irm.validate_capsule( **capsule_dict )
                status = capsule_dict.get( 'status', 'error' )
                if status == 'ok':
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action='import_capsule',
                                                                      **capsule_dict ) )
                else:
                    message = 'The capsule contents are invalid and cannot be imported:<br/>%s' % \
                        str( capsule_dict.get( 'error_message', '' ) )
        return trans.fill_template( '/webapps/tool_shed/repository/upload_capsule.mako',
                                    url=url,
                                    message=message,
                                    status=status )

    @web.expose
    def view_changelog( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        changesets = []
        for changeset in repo.changelog:
            ctx = repo.changectx( changeset )
            if suc.get_repository_metadata_by_changeset_revision( trans.app, id, str( ctx ) ):
                has_metadata = True
            else:
                has_metadata = False
            change_dict = { 'ctx' : ctx,
                            'rev' : str( ctx.rev() ),
                            'date' : date,
                            'display_date' : hg_util.get_readable_ctx_date( ctx ),
                            'description' : ctx.description(),
                            'files' : ctx.files(),
                            'user' : ctx.user(),
                            'parent' : ctx.parents()[0],
                            'has_metadata' : has_metadata }
            # Make sure we'll view latest changeset first.
            changesets.insert( 0, change_dict )
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              id,
                                                                                              repository.tip( trans.app ),
                                                                                              metadata_only=True )
        return trans.fill_template( '/webapps/tool_shed/repository/view_changelog.mako',
                                    repository=repository,
                                    metadata=metadata,
                                    changesets=changesets,
                                    message=message,
                                    status=status )

    @web.expose
    def view_changeset( self, trans, id, ctx_str, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        ctx = hg_util.get_changectx_for_changeset( repo, ctx_str )
        if ctx is None:
            message = "Repository does not include changeset revision '%s'." % str( ctx_str )
            status = 'error'
            return trans.response.send_redirect( web.url_for( controller='repository',
                                                              action='view_changelog',
                                                              id=id,
                                                              message=message,
                                                              status=status ) )
        ctx_parent = ctx.parents()[ 0 ]
        if ctx.children():
            ctx_child = ctx.children()[ 0 ]
        else:
            ctx_child = None
        diffs = []
        options_dict = hg_util.get_mercurial_default_options_dict( 'diff' )
        # Not quite sure if the following settings make any difference, but with a combination of them and the size check on each
        # diff, we don't run out of memory when viewing the changelog of the cisortho2 repository on the test tool shed.
        options_dict[ 'maxfile' ] = basic_util.MAXDIFFSIZE
        options_dict[ 'maxtotal' ] = basic_util.MAXDIFFSIZE
        diffopts = mdiff.diffopts( **options_dict )
        for diff in patch.diff( repo, node1=ctx_parent.node(), node2=ctx.node(), opts=diffopts ):
            if len( diff ) > basic_util.MAXDIFFSIZE:
                diff = util.shrink_string_by_size( diff, basic_util.MAXDIFFSIZE )
            diffs.append( basic_util.to_html_string( diff ) )
        modified, added, removed, deleted, unknown, ignored, clean = repo.status( node1=ctx_parent.node(), node2=ctx.node() )
        anchors = modified + added + removed + deleted + unknown + ignored + clean
        metadata = metadata_util.get_repository_metadata_by_repository_id_changeset_revision( trans.app,
                                                                                              id,
                                                                                              ctx_str,
                                                                                              metadata_only=True )
        # For rendering the prev button.
        if ctx_parent:
            ctx_parent_date = hg_util.get_readable_ctx_date( ctx_parent )
            ctx_parent_rev = ctx_parent.rev()
            if ctx_parent_rev < 0:
                 prev = None
            else:
                prev = "<b>%s:%s</b> <i>(%s)</i>" % ( ctx_parent_rev, ctx_parent, ctx_parent_date )
        else:
           prev = None
        if ctx_child:
            ctx_child_date = hg_util.get_readable_ctx_date( ctx_child )
            ctx_child_rev = ctx_child.rev()
            next = "<b>%s:%s</b> <i>(%s)</i>" % ( ctx_child_rev, ctx_child, ctx_child_date )
        else:
            next = None
        return trans.fill_template( '/webapps/tool_shed/repository/view_changeset.mako',
                                    repository=repository,
                                    metadata=metadata,
                                    prev=prev,
                                    next=next,
                                    ctx=ctx,
                                    ctx_parent=ctx_parent,
                                    ctx_child=ctx_child,
                                    anchors=anchors,
                                    modified=modified,
                                    added=added,
                                    removed=removed,
                                    deleted=deleted,
                                    unknown=unknown,
                                    ignored=ignored,
                                    clean=clean,
                                    diffs=diffs,
                                    message=message,
                                    status=status )

    @web.expose
    def view_or_manage_repository( self, trans, **kwd ):
        repository_id = kwd.get( 'id', None )
        if repository_id:
            repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
            user = trans.user
            if repository:
                if user is not None and ( trans.user_is_admin() or \
                                          trans.app.security_agent.user_can_administer_repository( user, repository ) ):
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action='manage_repository',
                                                                      **kwd ) )
                else:
                    return trans.response.send_redirect( web.url_for( controller='repository',
                                                                      action='view_repository',
                                                                      **kwd ) )
            return trans.show_error_message( "Invalid repository id '%s' received." % repository_id )
        return trans.show_error_message( "The repository id was not received." )

    @web.expose
    def view_repository( self, trans, id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        repository = suc.get_repository_in_tool_shed( trans.app, id )
        repo = hg_util.get_repo_for_repository( trans.app, repository=repository, repo_path=None, create=False )
        avg_rating, num_ratings = self.get_ave_item_rating_data( trans.sa_session, repository, webapp_model=trans.model )
        changeset_revision = kwd.get( 'changeset_revision', repository.tip( trans.app ) )
        repository.share_url = suc.generate_sharable_link_for_repository_in_tool_shed( repository, changeset_revision=changeset_revision )
        repository.clone_url = common_util.generate_clone_url_for_repository_in_tool_shed( trans.user, repository )
        display_reviews = kwd.get( 'display_reviews', False )
        alerts = kwd.get( 'alerts', '' )
        alerts_checked = CheckboxField.is_checked( alerts )
        if repository.email_alerts:
            email_alerts = json.loads( repository.email_alerts )
        else:
            email_alerts = []
        repository_dependencies = None
        user = trans.user
        if user and kwd.get( 'receive_email_alerts_button', False ):
            flush_needed = False
            if alerts_checked:
                if user.email not in email_alerts:
                    email_alerts.append( user.email )
                    repository.email_alerts = json.dumps( email_alerts )
                    flush_needed = True
            else:
                if user.email in email_alerts:
                    email_alerts.remove( user.email )
                    repository.email_alerts = json.dumps( email_alerts )
                    flush_needed = True
            if flush_needed:
                trans.sa_session.add( repository )
                trans.sa_session.flush()
        checked = alerts_checked or ( user and user.email in email_alerts )
        alerts_check_box = CheckboxField( 'alerts', checked=checked )
        changeset_revision_select_field = grids_util.build_changeset_revision_select_field( trans,
                                                                                            repository,
                                                                                            selected_value=changeset_revision,
                                                                                            add_id_to_name=False,
                                                                                            downloadable=False )
        revision_label = hg_util.get_revision_label( trans.app, repository, changeset_revision, include_date=False )
        repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, id, changeset_revision )
        if repository_metadata:
            metadata = repository_metadata.metadata
            # Get a dictionary of all repositories upon which the contents of the current repository_metadata record depend.
            toolshed_base_url = str( web.url_for( '/', qualified=True ) ).rstrip( '/' )
            rb = relation_builder.RelationBuilder( trans.app, repository, repository_metadata, toolshed_base_url )
            repository_dependencies = rb.get_repository_dependencies_for_changeset_revision()
            if str( repository.type ) != rt_util.TOOL_DEPENDENCY_DEFINITION:
                # Handle messaging for orphan tool dependency definitions.
                dd = dependency_display.DependencyDisplayer( trans.app )
                orphan_message = dd.generate_message_for_orphan_tool_dependencies( repository, metadata )
                if orphan_message:
                    message += orphan_message
                    status = 'warning'
        else:
            metadata = None
        is_malicious = metadata_util.is_malicious( trans.app, id, repository.tip( trans.app ) )
        if is_malicious:
            if trans.app.security_agent.can_push( trans.app, trans.user, repository ):
                message += malicious_error_can_push
            else:
                message += malicious_error
            status = 'error'
        tsucm = ToolShedUtilityContainerManager( trans.app )
        containers_dict = tsucm.build_repository_containers( repository,
                                                             changeset_revision,
                                                             repository_dependencies,
                                                             repository_metadata )
        repository_type_select_field = rt_util.build_repository_type_select_field( trans, repository=repository )
        heads = hg_util.get_repository_heads( repo )
        return trans.fill_template( '/webapps/tool_shed/repository/view_repository.mako',
                                    repo=repo,
                                    heads=heads,
                                    repository=repository,
                                    repository_metadata=repository_metadata,
                                    metadata=metadata,
                                    containers_dict=containers_dict,
                                    avg_rating=avg_rating,
                                    display_reviews=display_reviews,
                                    num_ratings=num_ratings,
                                    alerts_check_box=alerts_check_box,
                                    changeset_revision=changeset_revision,
                                    changeset_revision_select_field=changeset_revision_select_field,
                                    revision_label=revision_label,
                                    repository_type_select_field=repository_type_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    def view_tool_metadata( self, trans, repository_id, changeset_revision, tool_id, **kwd ):
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        render_repository_actions_for = kwd.get( 'render_repository_actions_for', 'tool_shed' )
        repository = suc.get_repository_in_tool_shed( trans.app, repository_id )
        repo_files_dir = repository.repo_path( trans.app )
        repo = hg_util.get_repo_for_repository( trans.app, repository=None, repo_path=repo_files_dir, create=False )
        tool_metadata_dict = {}
        tool_lineage = []
        tool = None
        guid = None
        original_tool_data_path = trans.app.config.tool_data_path
        revision_label = hg_util.get_revision_label( trans.app, repository, changeset_revision, include_date=False )
        repository_metadata = suc.get_repository_metadata_by_changeset_revision( trans.app, repository_id, changeset_revision )
        if repository_metadata:
            repository_metadata_id = trans.security.encode_id( repository_metadata.id )
            metadata = repository_metadata.metadata
            if metadata:
                if 'tools' in metadata:
                    tv = tool_validator.ToolValidator( trans.app )
                    for tool_metadata_dict in metadata[ 'tools' ]:
                        if tool_metadata_dict[ 'id' ] == tool_id:
                            work_dir = tempfile.mkdtemp()
                            relative_path_to_tool_config = tool_metadata_dict[ 'tool_config' ]
                            guid = tool_metadata_dict[ 'guid' ]
                            full_path_to_tool_config = os.path.abspath( relative_path_to_tool_config )
                            full_path_to_dir, tool_config_filename = os.path.split( full_path_to_tool_config )
                            can_use_disk_file = tv.can_use_tool_config_disk_file( repository,
                                                                                  repo,
                                                                                  full_path_to_tool_config,
                                                                                  changeset_revision )
                            if can_use_disk_file:
                                trans.app.config.tool_data_path = work_dir
                                tool, valid, message, sample_files = \
                                    tv.handle_sample_files_and_load_tool_from_disk( repo_files_dir,
                                                                                    repository_id,
                                                                                    full_path_to_tool_config,
                                                                                    work_dir )
                                if message:
                                    status = 'error'
                            else:
                                tool, message, sample_files = \
                                    tv.handle_sample_files_and_load_tool_from_tmp_config( repo,
                                                                                          repository_id,
                                                                                          changeset_revision,
                                                                                          tool_config_filename,
                                                                                          work_dir )
                                if message:
                                    status = 'error'
                            basic_util.remove_dir( work_dir )
                            break
                    if guid:
                        tvm = tool_version_manager.ToolVersionManager( trans.app )
                        tool_lineage = tvm.get_version_lineage_for_tool( repository_id,
                                                                         repository_metadata,
                                                                         guid )
        else:
            repository_metadata_id = None
            metadata = None
        changeset_revision_select_field = grids_util.build_changeset_revision_select_field( trans,
                                                                                            repository,
                                                                                            selected_value=changeset_revision,
                                                                                            add_id_to_name=False,
                                                                                            downloadable=False )
        trans.app.config.tool_data_path = original_tool_data_path
        return trans.fill_template( "/webapps/tool_shed/repository/view_tool_metadata.mako",
                                    render_repository_actions_for=render_repository_actions_for,
                                    repository=repository,
                                    repository_metadata_id=repository_metadata_id,
                                    metadata=metadata,
                                    tool=tool,
                                    tool_metadata_dict=tool_metadata_dict,
                                    tool_lineage=tool_lineage,
                                    changeset_revision=changeset_revision,
                                    revision_label=revision_label,
                                    changeset_revision_select_field=changeset_revision_select_field,
                                    message=message,
                                    status=status )

    @web.expose
    def view_workflow( self, trans, workflow_name, repository_metadata_id, **kwd ):
        """Retrieve necessary information about a workflow from the database so that it can be displayed in an svg image."""
        message = escape( kwd.get( 'message', '' ) )
        status = kwd.get( 'status', 'done' )
        render_repository_actions_for = kwd.get( 'render_repository_actions_for', 'tool_shed' )
        if workflow_name:
            workflow_name = encoding_util.tool_shed_decode( workflow_name )
        repository_metadata = metadata_util.get_repository_metadata_by_id( trans.app, repository_metadata_id )
        repository = suc.get_repository_in_tool_shed( trans.app, trans.security.encode_id( repository_metadata.repository_id ) )
        changeset_revision = repository_metadata.changeset_revision
        metadata = repository_metadata.metadata
        return trans.fill_template( "/webapps/tool_shed/repository/view_workflow.mako",
                                    repository=repository,
                                    render_repository_actions_for=render_repository_actions_for,
                                    changeset_revision=changeset_revision,
                                    repository_metadata_id=repository_metadata_id,
                                    workflow_name=workflow_name,
                                    metadata=metadata,
                                    message=message,
                                    status=status )
