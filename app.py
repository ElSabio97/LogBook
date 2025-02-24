import streamlit as st
from functions import (descargar_y_actualizar_csv, 
                       update_file_in_drive_by_name, 
                       descargar_csv, 
                       rellenar_y_combinar_pdfs
                       )

FOLDER_ID = '1B8gnCmbBaGMBT77ba4ntjpZj_NkJcvuI'  # Drive folder ID

def main():
    st.title("LogBook")
    st.write("Hola, sube el registro de Air Europa Express para ir actualizando tu LogBook.")
    file_uploader = st.file_uploader("label", type="xls", label_visibility="hidden")
    
    if st.button("Subir datos") and file_uploader is not None:
        user_data = descargar_y_actualizar_csv('LogBook.csv', FOLDER_ID, file_uploader)
        if user_data is None or len(user_data) < 2:
            st.write("El archivo está vacío o no se pudo descargar.")
        else:
            st.write(user_data)
            user_data.to_csv('Actualizado.csv', index=False, sep=';', encoding='UTF-8')
            local_path = 'Actualizado.csv'
            update_file_in_drive_by_name('LogBook.csv', FOLDER_ID, local_path)
            st.write("Archivo actualizado y subido a Google Drive.")
            
    # If the user clicks the button "Ver datos", the file will be downloaded and if the download is successful, a "Descargar Logbook" button will appear
    # to download the LogBook.pdf file. But only when "Descargar LogBook" is clicked, the fucntion rellenar_y_combinar_pdfs will be executed
    if st.button("Ver datos"):
        user_data = descargar_csv('LogBook.csv', FOLDER_ID)
        
        if user_data is not None:
            pdf_path = rellenar_y_combinar_pdfs("LogBook_Rellenable.pdf", "LogBook_Rellenado.pdf", user_data)
            with open(pdf_path, "rb") as pdf_file:
                pdf_data = pdf_file.read()

            if st.download_button(
                label="Descargar LogBook",
                data=pdf_data,
                file_name='LogBook.pdf',
                mime='application/pdf'
            ):
                st.write("¡LogBook descargado!")
        else:
            st.write("No se ha podido actualizar el archivo.")
            st.write(user_data)

if __name__ == "__main__":
    main()
