/** Real-time Communication feature **/
define(['mvc/ui/ui-modal'], function( Modal ) {

var GenericNavView = Backbone.View.extend({

    initialize: function ( options ) {
        this.type = options.type;
        this.modal = null;
    },

    /** makes bootstrap modal and iframe inside it */
    makeModalIframe: function( e ) {
	// make modal
	var host =  window.Galaxy.config.communication_server_host,
	    port = window.Galaxy.config.communication_server_port,
	    username = escape( window.Galaxy.user.attributes.username ),
	    persistent_communication_rooms = escape( window.Galaxy.config.persistent_communication_rooms ),
	    query_string = "?username=" + username + "&persistent_communication_rooms=" + persistent_communication_rooms,
	    src = host + ":" + port + query_string,
	    $el_chat_modal_header = null,
	    $el_chat_modal_body = null,
            iframe_template = '<iframe class="f-iframe fade in" src="' + src + '" style="width:100%; height:100%;"> </iframe>',
            header_template  = '<i class="fa fa-comment" aria-hidden="true" title="Communicate with other users"></i>' +
	                       '<i class="fa fa-times close-modal" aria-hidden="true" ' +
                               'style="float: right; cursor: pointer;" title="Close"></i>';
 
	// deletes the chat modal if already present and create one
        if( $( '.chat-modal' ).length > 0 ) {
            $( '.chat-modal' ).remove();
	}
        // creates a modal
	GenericNavView.modal = new Modal.View({
	    body            : iframe_template,
	    height          : 350,
	    width           : 600,
	    closing_events  : true,
	    title_separator : false,
            cls             : 'ui-modal chat-modal'
	});

	// shows modal
	GenericNavView.modal.show();
        $el_chat_modal_header = $( '.chat-modal .modal-header' );
        $el_chat_modal_body = $( '.chat-modal .modal-body' );
	// adjusts the css of bootstrap modal for chat
	$el_chat_modal_header.css( 'padding', '3px' );
	$el_chat_modal_body.css( 'padding', '2px' );
	$el_chat_modal_header.find( 'h4' ).remove();
	$el_chat_modal_header.removeAttr( 'min-height' ).removeAttr( 'padding' ).removeAttr( 'border' );
	$el_chat_modal_header.append( header_template );
	// click event of the close button for chat
	$( '.close-modal' ).click(function( e ) {
	    $( '.chat-modal' ).css( 'display', 'none' );
	});
    },

    /**renders the chat icon as a nav item*/
    render: function() {
        var self = this,
            navItem = {};
        if( self.type === 'chat' ) {
            navItem = {
                id              : 'show-chat-online',
                icon            : 'fa-comment-o',
                tooltip         : 'Chat online',
                visible         : false,
                onclick         : self.makeModalIframe
            }
            return navItem;
        }
    }
});

return {
    GenericNavView  : GenericNavView
};

});

