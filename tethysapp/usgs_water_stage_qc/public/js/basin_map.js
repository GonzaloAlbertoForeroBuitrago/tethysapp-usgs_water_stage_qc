function customPropertiesGenerator(feature, layer) {
  let properties = feature.getProperties();
    return "<table class='table table-striped table-bordered table-condensed'>" +
        "<tr><th>Gage ID</th><td>" + properties.gage_id + "</td></tr>" +
        "</table>" +
        "<button class='btn btn-primary' onclick='window.location.href = \"" + properties.gage_id + "\"'>Go to page</button>";
}

$(function() { //wait for page to load

  MAP_LAYOUT.properties_table_generator(customPropertiesGenerator);
});