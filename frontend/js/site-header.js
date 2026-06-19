/* Cash in Flash — site header + mobile menu (matches cashinflash.com). */
(function () {
  'use strict';

  /* Sticky header shadow */
  var header = document.getElementById('site-header');
  if (header && 'IntersectionObserver' in window) {
    var sentinel = document.createElement('div');
    sentinel.style.cssText = 'position:absolute;top:0;left:0;width:1px;height:10px;pointer-events:none';
    sentinel.setAttribute('aria-hidden', 'true');
    document.body.prepend(sentinel);
    var hdrObserver = new IntersectionObserver(function (entries) {
      header.classList.toggle('scrolled', !entries[0].isIntersecting);
    }, { threshold: 0 });
    hdrObserver.observe(sentinel);
  } else if (header) {
    window.addEventListener('scroll', function () {
      header.classList.toggle('scrolled', window.scrollY > 10);
    }, { passive: true });
  }

  /* Mobile menu */
  var toggle = document.getElementById('menu-toggle');
  var mobileMenu = document.getElementById('mobile-menu');
  var overlay = document.getElementById('mobile-overlay');
  if (!toggle || !mobileMenu) return;

  function openMenu() {
    toggle.classList.add('active');
    mobileMenu.classList.add('open');
    if (overlay) overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function closeMenu() {
    toggle.classList.remove('active');
    mobileMenu.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  toggle.addEventListener('click', function () {
    mobileMenu.classList.contains('open') ? closeMenu() : openMenu();
  });
  if (overlay) overlay.addEventListener('click', closeMenu);
  var closeBtn = document.getElementById('mobile-menu-close');
  if (closeBtn) closeBtn.addEventListener('click', closeMenu);

  /* Mobile sub-menu toggles */
  document.querySelectorAll('.mobile-nav-item.has-sub > a').forEach(function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      this.parentElement.classList.toggle('open');
    });
  });
})();
