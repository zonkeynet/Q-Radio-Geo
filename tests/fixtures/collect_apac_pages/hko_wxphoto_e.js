var aws_stn;

document.write('<p>');
document.write('<div class="w3-container">');
document.write('<button onclick="my(\'Demo1\')" class="w3-button w3-blue1 w3-left-align">Weather Information</button><br>');
document.write('<div id="Demo1" class="w3-hide">');
document.write('<ul class="w3-ul">');

// 20181214 - add cwb
// 20190319 - add cp1 & lam
if ( stn == "cch" || stn == "hko" || stn == "hk2" || stn == "dnl" || stn == "pe2" || stn == "wlp" || stn == "wgl" || stn == "wl2" || stn == "tpk" || stn == "skg" || stn == "sk2" || stn == "cce" || stn == "klt" || stn == "lfs" || stn == "cwa" || stn == "cwb" || stn == "cp1" || stn == "lam") {														
   aws_stn = stn;
   if (stn == "hk2") { aws_stn = "hko"; }
   if (stn == "dnl") { aws_stn = "pen"; }
   if (stn == "pe2") { aws_stn = "pen"; }
   if (stn == "wl2") { aws_stn = "wgl"; }
   if (stn == "sk2") { aws_stn = "skg"; }
   if (stn == "cce") { aws_stn = "ccb"; }
   if (stn == "cwa") { aws_stn = "cwb"; }
 
// 20190319   
   if (aws_stn == "ccb" || aws_stn == "tpk" || stn == "cp1" || aws_stn == "lam")
       document.write('<li><A title="Time Series of Weather Information" href="../windbarb.htm?'+aws_stn+'&amp;&menu=otherwxi&rwx&addbar" alt="Time Series of Weather Information">Time Series of Weather Information</A></li>');
   else
       document.write('<li><A title="Time Series of Weather Information" href="../display_graph.htm?'+aws_stn+'&amp;" alt="Time Series of Weather Information">Time Series of Weather Information</A></li>');
}

if ( stn == "swh" || stn == "cp1" || stn == "wgl" || stn == "wl2" ) {
   aws_stn = stn;
   if (stn == "wl2") { aws_stn = "wgl"; }
   document.write('<li><A title="Automatic Visibility Reading" href="../display_element_vis.htm#'+aws_stn+'" alt="Automatic Visibility Reading">Automatic Visibility Reading</A></li>');
} 

