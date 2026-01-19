// Active navigation state management
const navLinks = document.querySelectorAll('.nav-links a');
const sections = document.querySelectorAll('.section');

// Function to update active nav link
function updateActiveNav() {
    let current = '';
    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;
        if (window.scrollY >= (sectionTop - 200)) {
            current = section.getAttribute('id');
        }
    });

    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${current}`) {
            link.classList.add('active');
        }
    });
}

// Listen for scroll events
window.addEventListener('scroll', updateActiveNav);

// Mobile menu toggle functionality
const menuToggle = document.getElementById('menuToggle');
const navLinksContainer = document.getElementById('navLinks');

menuToggle.addEventListener('click', () => {
    navLinksContainer.classList.toggle('active');
});

// Close mobile menu when clicking on a link
navLinks.forEach(link => {
    link.addEventListener('click', () => {
        navLinksContainer.classList.remove('active');
    });
});

// Close mobile menu when clicking outside
document.addEventListener('click', (e) => {
    if (!menuToggle.contains(e.target) && !navLinksContainer.contains(e.target)) {
        navLinksContainer.classList.remove('active');
    }
});

// FilePond initialization and file upload for each section
FilePond.registerPlugin(
    FilePondPluginFileEncode,
    FilePondPluginFileValidateSize,
    FilePondPluginImageExifOrientation,
    FilePondPluginImagePreview
);

// Initialize FilePond instances
const pondDelete = FilePond.create(document.querySelector('.filepond-delete'), {
    allowMultiple: false,
    maxFileSize: '30MB',
    maxFiles: 1,
    acceptedFileTypes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel']
});

const pondChangePrice = FilePond.create(document.querySelector('.filepond-change-price'), {
    allowMultiple: false,
    maxFileSize: '30MB',
    maxFiles: 1,
    acceptedFileTypes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel']
});

const pondUpload = FilePond.create(document.querySelector('.filepond-upload'), {
    allowMultiple: true,
    maxFileSize: '30MB',
    maxFiles: 3,
    acceptedFileTypes: ['image/*', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel']
});

// Function to clean file names (similar to slugify)
function cleanFilename(filename) {
    const extension = filename.split('.').pop();
    let name = filename.substring(0, filename.lastIndexOf('.'));

    name = name.replace(/\s+/g, '-');
    name = name.replace(/[%?\/\\*<>|:"'#,;@&=+~]/g, '');

    const cyrillicToLatin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
        'я': 'ya', 'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N',
        'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh',
        'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E',
        'Ю': 'Yu', 'Я': 'Ya'
    };
    name = name.split('').map(char => cyrillicToLatin[char] || char).join('');

    name = name.replace(/[^a-zA-Z0-9-_]/g, '');
    if (!name) name = 'file';

    return `${name}.${extension.toLowerCase()}`;
}

// Handle file upload for each section
document.getElementById('upload-button-delete').addEventListener('click', async () => {
    const files = pondDelete.getFiles();
    if (files.length === 0) {
        document.getElementById('upload-message-delete').textContent = 'Please select a file.';
        return;
    }

    const formData = new FormData();
    files.forEach(file => {
        const cleanName = cleanFilename(file.filename);
        const cleanFile = new File([file.file], cleanName, { type: file.file.type });
        formData.append('files', cleanFile);
    });

    try {
        const response = await fetch('/delete-upload', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            document.getElementById('upload-message-delete').textContent = `Successfully uploaded ${files.length} file(s).`;
            pondDelete.removeFiles();
        } else {
            document.getElementById('upload-message-delete').textContent = 'Error uploading files. Please try again.';
        }
    } catch (error) {
        document.getElementById('upload-message-delete').textContent = 'Network error. Please check your connection.';
    }
});

document.getElementById('upload-button-change-price').addEventListener('click', async () => {
    const files = pondChangePrice.getFiles();
    if (files.length === 0) {
        document.getElementById('upload-message-change-price').textContent = 'Please select a file.';
        return;
    }

    const formData = new FormData();
    files.forEach(file => {
        const cleanName = cleanFilename(file.filename);
        const cleanFile = new File([file.file], cleanName, { type: file.file.type });
        formData.append('files', cleanFile);
    });

    try {
        const response = await fetch('/change-price-upload', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            document.getElementById('upload-message-change-price').textContent = `Successfully uploaded ${files.length} file(s).`;
            pondChangePrice.removeFiles();
        } else {
            document.getElementById('upload-message-change-price').textContent = 'Error uploading files. Please try again.';
        }
    } catch (error) {
        document.getElementById('upload-message-change-price').textContent = 'Network error. Please check your connection.';
    }
});

document.getElementById('upload-button-upload').addEventListener('click', async () => {
    const files = pondUpload.getFiles();
    console.log(files);
    if (files.length === 0) {
        document.getElementById('upload-message-upload').textContent = 'Please select at least one file.';
        return;
    }

    const formData = new FormData();
    files.forEach(file => {
        const cleanName = cleanFilename(file.filename);
        const cleanFile = new File([file.file], cleanName, { type: file.file.type });
        formData.append('files', cleanFile);
    });

    try {
        const response = await fetch('/upload-upload', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            document.getElementById('upload-message-upload').textContent = `Successfully uploaded ${files.length} file(s).`;
            pondUpload.removeFiles();
        } else {
            document.getElementById('upload-message-upload').textContent = 'Error uploading files. Please try again.';
        }
    } catch (error) {
        document.getElementById('upload-message-upload').textContent = 'Network error. Please check your connection.';
    }
});
