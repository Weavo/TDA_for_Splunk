require([
    'underscore',
    'jquery',
    'splunkjs/mvc',
    'splunkjs/mvc/simplexml/ready!'
], function(_, $, mvc) {

    // constants
    const authHeader = "Strava Authorization Token Request";
    const errorHeader = 'Error';
    const successHeader = 'Success';

    // define modal
    var $msgModal = $('#msgModal').modal({backdrop : false, show : false, keyboard : false});
    
    // sets content of modal in dashboard
    showMsg = function (header, text) {
        $msgModal
        .find('.modal-header').text(header).end()
        .find('.modal-body').text(text).end()
        .modal('show')
    };
    
    function authContent() {
        // prints modal-body html to dashboard         
        document.getElementById('bodyContent').innerHTML = "<p>Clicking \"Submit\" will redirect your browser to Strava\'s authorization website. \
                                                            Proceding the redirect, you will be prompted to do the following: \
                                                            \
                                                            <ol> \
                                                                <li>Provide login credentials to Strava.</li> \
                                                                <li>Click \"Authorize\" to request an access token.</li> \
                                                                <li>Log back into Splunk Web.</li> \
                                                            </ol></p>";
        // prints modal-footer html to dashboard
        document.getElementById('footerContent').innerHTML = "<button type=\"button\" class=\"btn btn-secondary\" data-dismiss=\"modal\">Close</button> \
                                                              <button id=\"postButton\" type=\"button\" class=\"btn btn-primary\">Submit</button>";
    }

    function errorContent() {
        document.getElementById('bodyContent').innerHTML = "Unable to redirect your browser to Strava\'s authorization page. \
                                                            Host is unable to access the public internet. \
                                                            Please check your internet connection and try again."

        document.getElementById('footerContent').innerHTML = "<button type=\"button\" class=\"btn btn-secondary\" data-dismiss=\"modal\">Close</button>"
    }

    // click event from "authorize" button in dashboard activates modal
    var btn = document.getElementById("modalButton");
    btn.onclick = function() {
        showMsg(authHeader, authContent());
    }

    window.onLoad=checkURL();

    // checks url for 'code' parameter and extracts it into variable.
    function checkURL() {
        var service = mvc.createService();
        var queryString = window.location.search;
        var urlParams = new URLSearchParams(queryString);
        var code = urlParams.get('code');

        // if 'code' exists in url, send it to the /strava/auth endpoint
        if (code != null) {

            var data = {"code":code};
            service.post('/strava/auth', data, function(err, response) {
                console.log(response)

                if(err) {
                    var errorMsg = 'Unable to obtain access token from Strava';
                    showMsg(errorHeader, errorMsg);

                } else if(response.status === 200) {
                    var successMsg = 'Successfully obtained access token from Strava.';
                    showMsg(successHeader, successMsg);
                }
            });
        } else {
            var data = {"output_mode":"json"};
            // request client id and client secret values from specified endpoint
            service.get('/data/inputs/strava/activities', data, function(err, response) {

                if(err) {
                    console.log('message: ', err);

                } else if(response.status === 200) {
                    // extract values from response and populate textbox fields in dashboard
                    client_id = response.data.entry[0].content.client_id;
                    client_secret = response.data.entry[0].content.client_secret;
                    document.getElementById('client_id').value = client_id;
                    document.getElementById('client_secret').value = client_secret;
                }   
            });
        }
    }
        
    // click event from the "submit" button in modal
    $(document.body).on('click', '#postButton', function(e) {

        // serializes values from textbox form fields
        e.preventDefault();
        var service = mvc.createService();
        var data = $('#userPOSTForm').serializeArray();
        var payload = {};

        // assigns keynames to values, stores them in dictionary
        _.each(data, function(field) {
            var key = field['name'];
            var value = field['value'];
            payload[key] = value;
        });

        // passes key/value dictionary to specified endpoint.
        service.post('/strava/auth', payload, function(err, response) {
            if(err) {
                showMsg(errorHeader, errorContent());
            } else if(response.status === 200) {
                // response is a URL, loads it into user's browser
                window.location.replace(response.data);
            } else {
                console.log('response: ', response.data);
            }
        });
    });
});