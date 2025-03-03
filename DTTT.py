import streamlit as st
import json
import re
import plistlib
import base64
# Hide GitHub icon and main menu (try one or both)
hide_css = """
#GithubIcon {
  visibility: hidden;
}

#MainMenu {
  visibility: hidden;
}
"""
st.markdown(hide_css, unsafe_allow_html=True)
##########################################
# Helper functions for color conversions #
##########################################

def rgb_to_hex(rgb_string: str) -> str:
    """
    Convert a space-separated string of floats (e.g. "0.5921568871 1 0.7960785031") 
    into a hex color string.
    """
    try:
        rgb_string = rgb_string.strip().strip("\x00")
        parts = rgb_string.split()
        rgb_values = list(map(float, parts))
        return "#{:02X}{:02X}{:02X}".format(
            int(rgb_values[0] * 255),
            int(rgb_values[1] * 255),
            int(rgb_values[2] * 255)
        )
    except Exception as e:
        return "Error"

def hex_to_rgb_floats(hex_str: str) -> str:
    """
    Convert a hex color (e.g. "#97FFCB") into a string of floats space-separated,
    e.g. "0.5921568871 1.0000000000 0.7960785031".
    """
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return ""
    r = int(hex_str[0:2], 16) / 255
    g = int(hex_str[2:4], 16) / 255
    b = int(hex_str[4:6], 16) / 255
    return f"{r:.10f} {g:.10f} {b:.10f}"

##########################################
# Conversion functions: JSON <-> Tana     #
##########################################

def json_to_tana(json_input: str) -> str:
    """
    Convert Figma JSON tokens to Tana Paste format with a "%%tana%%" header.
    For color tokens, the leading '#' is removed.
    """
    try:
        data = json.loads(json_input)
    except Exception as e:
        return f"Error parsing JSON: {e}"
    
    output = "%%tana%%\n\n"
    for token_name, token_data in data.items():
        token_type = token_data.get('$type', '')
        token_value = token_data.get('$value', '')
        # Remove leading '#' for color tokens.
        if token_type.lower() == "color" and isinstance(token_value, str) and token_value.startswith("#"):
            token_value = token_value[1:]
        output += f"- {token_name} #[[Design Token]]\n"
        output += f"  - Type:: {token_type}\n"
        output += f"  - Value:: {token_value}\n\n"
    return output

def tana_to_json(tana_input: str) -> str:
    """
    Convert Tana Paste format tokens back into Figma JSON tokens.
    For color tokens, re-add the leading '#' to the value.
    """
    lines = [line for line in tana_input.splitlines() if line.strip() != ""]
    if lines and lines[0].strip() == "%%tana%%":
        lines = lines[1:]
    tana_body = "\n".join(lines)
    
    # Split tokens by detecting lines starting with "- " at the beginning.
    tokens = re.split(r'(?m)^(?=- )', tana_body)
    tokens = [t.strip() for t in tokens if t.strip()]
    
    result = {}
    for token in tokens:
        token_lines = token.splitlines()
        if not token_lines:
            continue
        header = token_lines[0].strip().lstrip("-").strip()
        token_name = re.sub(r'#\[\[.*?\]\]', '', header).strip()
        token_dict = {}
        for line in token_lines[1:]:
            line = line.strip()
            if line.startswith("-") and "::" in line:
                line_content = line.lstrip("-").strip()
                field, value = line_content.split("::", 1)
                field = field.strip()
                value = value.strip()
                if field.lower() == "type":
                    token_dict["$type"] = value
                elif field.lower() == "value":
                    token_dict["raw_value"] = value
                else:
                    token_dict[field] = value
        if token_dict.get("$type", "").lower() == "color":
            raw_val = token_dict.get("raw_value", "")
            if not raw_val.startswith("#"):
                token_dict["$value"] = "#" + raw_val
            else:
                token_dict["$value"] = raw_val
        else:
            raw_val = token_dict.get("raw_value", "")
            try:
                numeric_val = float(raw_val)
                if numeric_val.is_integer():
                    token_dict["$value"] = int(numeric_val)
                else:
                    token_dict["$value"] = numeric_val
            except:
                token_dict["$value"] = raw_val
        if "raw_value" in token_dict:
            del token_dict["raw_value"]
        result[token_name] = token_dict
    try:
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error generating JSON: {e}"

##########################################
# Conversion functions: Affinity (.clr)   #
##########################################

def affinity_to_json(uploaded_file) -> str:
    """
    Convert an Affinity .clr file (binary plist) into intermediate JSON.
    Extracts color names and NSRGB values, converts to hex, and skips any "$null" names.
    """
    try:
        data = plistlib.loads(uploaded_file.read())
    except Exception as e:
        return f"Error reading plist: {e}"
    
    objects = data.get("$objects", [])
    # Collect potential color names (strings)
    names = [obj for obj in objects if isinstance(obj, str)]
    # Collect NSRGB dictionaries: objects with key "NSRGB"
    rgb_dicts = [obj for obj in objects if isinstance(obj, dict) and "NSRGB" in obj]
    
    tokens = {}
    for name, rgb_obj in zip(names, rgb_dicts):
        if name == "$null":
            continue
        nsrgb = rgb_obj.get("NSRGB", b"")
        try:
            rgb_str = nsrgb.decode("utf-8").strip().strip("\x00")
            hex_val = rgb_to_hex(rgb_str)
            tokens[name] = {
                "$type": "color",
                "$value": hex_val
            }
        except Exception as e:
            tokens[name] = {
                "$type": "color",
                "$value": "Error"
            }
    return json.dumps(tokens, indent=2)

def json_to_affinity(json_input: str) -> bytes:
    """
    Convert intermediate JSON tokens (assumed to be color tokens) into an Affinity .clr file.
    Builds a minimal plist structure with a "$objects" list that alternates between a placeholder and
    the token name and NSRGB dictionary.
    """
    try:
        data = json.loads(json_input)
    except Exception as e:
        st.error(f"Error parsing JSON: {e}")
        return None

    objects_list = ["$null"]  # First element placeholder
    for name, token in data.items():
        if token.get("$type", "").lower() == "color":
            hex_val = token.get("$value", "")
            rgb_str = hex_to_rgb_floats(hex_val)
            objects_list.append(name)
            objects_list.append({"NSRGB": rgb_str.encode("utf-8")})
    plist_dict = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"NSColors": 1},
        "$objects": objects_list
    }
    try:
        return plistlib.dumps(plist_dict, fmt=plistlib.FMT_BINARY)
    except Exception as e:
        st.error(f"Error generating plist: {e}")
        return None

##########################################
# Conversion functions: Adobe (ASE)         #
##########################################

def adobe_to_json(uploaded_file) -> str:
    """
    Placeholder for Adobe ASE to JSON conversion.
    """
    return "Adobe ASE to JSON conversion not implemented yet."

def json_to_adobe(json_input: str) -> str:
    """
    Placeholder for JSON to Adobe ASE conversion.
    """
    return "JSON to Adobe ASE conversion not implemented yet."

##########################################
# Main App: Two Dropdowns for Source & Target
##########################################

def main():
    st.title("Multi-Converter: Design Tokens")
    st.write("Convert design tokens between various formats using an intermediate JSON format as the hub.")
    
    formats = ["Affinity (.clr)", "Figma JSON", "Tana Paste", "Adobe ASE"]
    
    source_format = st.selectbox("Source Format", formats, index=1)  # Default Figma JSON
    target_format = st.selectbox("Target Format", formats, index=2)  # Default Tana Paste
    
    st.markdown("---")
    
    # If the source is file-based, show uploader; else text area.
    if source_format in ["Affinity (.clr)", "Adobe ASE"]:
        uploaded_file = st.file_uploader("Upload Source File", type=["clr", "ase"])
        source_data = None
        if uploaded_file is not None:
            source_data = uploaded_file
    else:
        source_data = st.text_area("Input Data", height=300)
    
    if st.button("Convert"):
        output = ""
        # Affinity (.clr) as source
        if source_format == "Affinity (.clr)" and target_format == "Figma JSON":
            if source_data is None:
                st.error("Please upload a .clr file.")
            else:
                output = affinity_to_json(source_data)
        elif source_format == "Affinity (.clr)" and target_format == "Tana Paste":
            if source_data is None:
                st.error("Please upload a .clr file.")
            else:
                intermediate = affinity_to_json(source_data)
                output = json_to_tana(intermediate)
        elif source_format == "Affinity (.clr)" and target_format == "Adobe ASE":
            st.error("Conversion from Affinity to Adobe ASE not implemented.")
        # Figma JSON as source
        elif source_format == "Figma JSON" and target_format == "Tana Paste":
            output = json_to_tana(source_data)
        elif source_format == "Figma JSON" and target_format == "Affinity (.clr)":
            plist_bytes = json_to_affinity(source_data)
            if plist_bytes is not None:
                b64 = base64.b64encode(plist_bytes).decode('utf-8')
                download_link = f"Download your .clr file: <a href='data:application/octet-stream;base64,{b64}' download='export.clr'>Download .clr File</a>"
                # Also generate XML representation for display:
                try:
                    plist_dict = plistlib.loads(plist_bytes)
                    xml_plist = plistlib.dumps(plist_dict, fmt=plistlib.FMT_XML).decode('utf-8')
                except Exception as e:
                    xml_plist = f"Error converting to XML: {e}"
                output = download_link + "\n\n" + "CLR File Contents (XML):\n" + xml_plist
        elif source_format == "Figma JSON" and target_format == "Adobe ASE":
            output = json_to_adobe(source_data)
        elif source_format == "Figma JSON" and target_format == "Figma JSON":
            output = source_data
        # Tana Paste as source
        elif source_format == "Tana Paste" and target_format == "Figma JSON":
            output = tana_to_json(source_data)
        elif source_format == "Tana Paste" and target_format == "Affinity (.clr)":
            intermediate = tana_to_json(source_data)
            plist_bytes = json_to_affinity(intermediate)
            if plist_bytes is not None:
                b64 = base64.b64encode(plist_bytes).decode('utf-8')
                download_link = f"Download your .clr file: <a href='data:application/octet-stream;base64,{b64}' download='export.clr'>Download .clr File</a>"
                try:
                    plist_dict = plistlib.loads(plist_bytes)
                    xml_plist = plistlib.dumps(plist_dict, fmt=plistlib.FMT_XML).decode('utf-8')
                except Exception as e:
                    xml_plist = f"Error converting to XML: {e}"
                output = download_link + "\n\n" + "CLR File Contents (XML):\n" + xml_plist
        elif source_format == "Tana Paste" and target_format == "Adobe ASE":
            output = "Conversion from Tana Paste to Adobe ASE not implemented yet."
        elif source_format == "Tana Paste" and target_format == "Tana Paste":
            output = source_data
        # Adobe ASE as source (placeholders)
        elif source_format == "Adobe ASE" and target_format == "Figma JSON":
            if source_data is None:
                st.error("Please upload an ASE file.")
            else:
                output = adobe_to_json(source_data)
        elif source_format == "Adobe ASE" and target_format == "Affinity (.clr)":
            st.error("Conversion from Adobe ASE to Affinity not implemented.")
        elif source_format == "Adobe ASE" and target_format == "Tana Paste":
            if source_data is None:
                st.error("Please upload an ASE file.")
            else:
                intermediate = adobe_to_json(source_data)
                output = json_to_tana(intermediate)
        elif source_format == "Adobe ASE" and target_format == "Adobe ASE":
            if source_data is None:
                st.error("Please upload an ASE file.")
            else:
                output = "No conversion needed."
        else:
            output = "This conversion is not implemented yet."
        
        # Display output
        if target_format in ["Affinity (.clr)", "Adobe ASE"] and "Download" in output:
            st.markdown(output, unsafe_allow_html=True)
        else:
            st.text_area("Output", value=output, height=300)

if __name__ == "__main__":
    main()
